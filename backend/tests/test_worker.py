"""worker：任務經過佇列執行、啟動時復原、去背、RAG 的啟動準備、品牌文件上傳、歷史回寫。需要 composer。"""

import asyncio
import io
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from saq.job import Status

from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiClient
from app.brands import load_brands
from app.contract import (
    FilePhoto,
    HistoryEntry,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    Price,
    Product,
    ProductCutout,
    ProductDraft,
    RagChunk,
)
from app.cutout.engine import CutoutEngine
from app.cutout.segmenter import Segmenter, SimSegmenter
from app.db.session import Database
from app.errors import Unavailable
from app.events import EventStore
from app.pipeline.gemini import GeminiAgent, GeminiReviewer
from app.pipeline.review import ComposerPosters, ComposerReviewer
from app.pipeline.sim import SimPosters, SimRetriever, SimReviewer, sim_ports
from app.queues import Queues, TaskFailed, cutout_key, ingest_channel
from app.rag.chunking import EMBED_DIMS, chunk_document, embed_preview, vector_preview
from app.rag.engine import RagEngine
from app.rag.history import history_chunk
from app.rag.retriever import BgeRetriever
from app.rag.state import RagMode
from app.rag.store import VectorStore
from app.rag.sync import SyncResult, chunk_metadata, index_text, sync_brand
from app.repo import catalog, history, jobs
from app.settings import ReviewMode, Settings
from app.worker import (
    RESTART_REASON,
    Services,
    build_services,
    build_workers,
    cutout,
    ingest,
    recover,
    requeue_cutouts_periodically,
    requeue_pending_cutouts,
    warm_up_rag,
    write_back,
)
from tests.conftest import TEST_CHROMA_DATABASE, TEST_REDIS_URL
from tests.fake_encoder import FakeEncoder, fake_engine
from tests.fixtures import BRANDS_DIR, load_fixture, selected_history

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    settings = Settings(
        _env_file=None,
        image_mode='sim',
        agent_mode='sim',
        data_dir=tmp_path / 'data',
        local_photos_dir=tmp_path / 'local',
        brands_dir=BRANDS_DIR,
    )
    cutouts = CutoutEngine('sim', tmp_path / 'models', redis)
    rag = RagEngine('sim', tmp_path / 'models', redis)
    vectors = VectorStore(settings.chroma_url, database=TEST_CHROMA_DATABASE)
    store = EventStore(db, redis)
    yield Services(db, redis, store, composer, ports, 0, settings, cutouts, rag, vectors)
    await composer.aclose()
    await db.truncate_all()


@pytest.fixture
async def queues(redis: Redis) -> AsyncIterator[Queues]:
    await redis.flushdb()
    q = Queues(TEST_REDIS_URL)
    await q.connect()
    yield q
    await q.disconnect()


@asynccontextmanager
async def running(services: Services, queues: Queues) -> AsyncIterator[None]:
    workers = build_workers(services, queues)
    started = [asyncio.create_task(w.start()) for w in workers]
    try:
        yield
    finally:
        for w in workers:
            await w.stop()
        await asyncio.gather(*started, return_exceptions=True)


async def queued_job(services: Services, job_id: str) -> None:
    data = load_fixture('timelines/selune-retry.json')
    async with services.db.session() as s:
        await jobs.create_job(s, job_id, JobInput.model_validate(data['input']), NOW)
    await services.store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await services.store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))


async def summary(services: Services, job_id: str) -> Any:
    async with services.db.session() as s:
        snap = await jobs.get_job(s, job_id)
    assert snap is not None
    return snap.summary


async def test_runs_queued_jobs_one_at_a_time(
    services: Services, queues: Queues, caplog: pytest.LogCaptureFixture
) -> None:
    await queued_job(services, 'job_w1')
    await queued_job(services, 'job_w2')
    await queues.enqueue_job('job_w1')
    await queues.enqueue_job('job_w2')
    await queues.enqueue_job('job_w1')
    # Lua 腳本快取是冷的時，worker 啟動的第一次 sweep 會晚於取工作；這裡重現那個情況
    await services.redis.script_flush()
    with caplog.at_level('INFO', logger='saq'):
        async with running(services, queues):
            for _ in range(150):
                if (await summary(services, 'job_w2')).finished:
                    break
                await asyncio.sleep(0.2)
    # 啟動時的 sweep 不能把剛取出、還沒標記為執行中的任務當成中斷的任務
    assert not [r.getMessage() for r in caplog.records if 'Sweeping job' in r.getMessage()]
    assert [(await summary(services, j)).stage for j in ('job_w1', 'job_w2')] == ['done', 'done']


async def test_recovery_fails_running_jobs_and_requeues_queued_ones(services: Services, queues: Queues) -> None:
    await queued_job(services, 'job_running')
    await services.store.append('job_running', JobStatusEvent(type='job.status', stage='rendering', round=1))
    await queued_job(services, 'job_waiting')
    await recover(services, queues)
    stopped = await summary(services, 'job_running')
    assert (stopped.stage, stopped.round, stopped.finished) == ('failed', 1, True)
    async with services.db.session() as s:
        snap = await jobs.get_job(s, 'job_running')
    assert snap is not None
    assert snap.events[-2]['reason'] == RESTART_REASON
    assert await queues.jobs.job('job_waiting') is not None


async def orphan(queues: Queues, job_id: str) -> None:
    """模擬 worker 在執行 run_job 時被強制終止：佇列紀錄停在 ACTIVE，也還留在 active 清單裡。"""
    await queues.enqueue_job(job_id)
    taken = await queues.jobs.dequeue(timeout=1)
    assert taken is not None and taken.key == job_id
    await taken.update(status=Status.ACTIVE)


async def test_recovery_requeues_a_queued_job_whose_queue_record_was_left_active(
    services: Services, queues: Queues
) -> None:
    await queued_job(services, 'job_orphan')
    await orphan(queues, 'job_orphan')
    await recover(services, queues)
    # 舊紀錄不能擋住重新排入
    record = await queues.jobs.job('job_orphan')
    assert record is not None and record.status == Status.QUEUED
    assert await queues.jobs.count('active') == 0
    async with running(services, queues):
        for _ in range(150):
            if (await summary(services, 'job_orphan')).finished:
                break
            await asyncio.sleep(0.2)
    assert (await summary(services, 'job_orphan')).stage == 'done'


async def test_recovery_aborts_the_queue_record_of_a_running_job(
    services: Services, queues: Queues, caplog: pytest.LogCaptureFixture
) -> None:
    await queued_job(services, 'job_dead')
    await services.store.append('job_dead', JobStatusEvent(type='job.status', stage='rendering', round=1))
    await orphan(queues, 'job_dead')
    await queued_job(services, 'job_idle')
    await queues.enqueue_job('job_idle')
    with caplog.at_level('WARNING', logger='app.worker'):
        await recover(services, queues)
    record = await queues.jobs.job('job_dead')
    assert record is not None and (record.status, record.error) == (Status.ABORTED, RESTART_REASON)
    # 紀錄要真的從 active 清單移除（只改狀態的話，系統狀態仍會算它執行中）
    assert await queues.jobs.count('active') == 0
    # worker 上次是當掉的：每放掉一筆紀錄記一則警告
    assert [r.getMessage() for r in caplog.records if r.name == 'app.worker'] == [
        '釋放前一個 worker 留下的佇列紀錄：job_dead'
    ]
    assert (await summary(services, 'job_dead')).stage == 'failed'
    # 其他狀態的紀錄不動
    waiting = await queues.jobs.job('job_idle')
    assert waiting is not None and waiting.status == Status.QUEUED


async def test_recovery_releases_the_queue_record_of_a_job_that_already_finished(
    services: Services, queues: Queues
) -> None:
    """worker 在任務的最後一個事件寫入之後、佇列標記完成之前當掉：資料庫裡的任務已結束，recover 不會逐筆看到它。"""
    await queued_job(services, 'job_finished')
    await services.store.append('job_finished', JobStatusEvent(type='job.status', stage='done', round=2))
    await orphan(queues, 'job_finished')
    await recover(services, queues)
    record = await queues.jobs.job('job_finished')
    assert record is not None and (record.status, record.error) == (Status.ABORTED, RESTART_REASON)
    assert await queues.jobs.count('active') == 0
    assert (await summary(services, 'job_finished')).stage == 'done'


PENDING = ProductCutout(model='BiRefNet-general', status='pending', url=None, error=None)


def photo_bytes(size: tuple[int, int] = (40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', size, (120, 80, 160)).save(buf, 'JPEG')
    return buf.getvalue()


async def photo_product(services: Services, url: str, source: str = 'upload', product_id: str | None = None) -> Product:
    """去背中的商品；照片檔由呼叫端寫入 data/ 或本機資料夾。"""
    async with services.db.session() as s:
        return await catalog.save_product(
            s,
            ProductDraft(
                id=product_id,
                brand_id='selune',
                name='晚安面膜',
                features=[],
                price=Price(sale=0, original=0),
                photo=FilePhoto.model_validate({'source': source, 'url': url}),
                cutout=PENDING,
            ),
            NOW,
        )


async def current(services: Services, product_id: str) -> Product:
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    assert product is not None
    return product


def write_upload(services: Services, name: str, data: bytes) -> str:
    folder = services.settings.data_dir / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f'/files/uploads/{name}'


async def test_cutout_runs_on_its_own_queue_and_writes_a_transparent_png(services: Services, queues: Queues) -> None:
    product = await photo_product(services, write_upload(services, 'mask.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    await queues.enqueue_cutout(product.id, product.photo.url)
    await queues.enqueue_cutout(product.id, product.photo.url)
    assert await queues.cutouts.count('queued') == 1
    async with running(services, queues):
        for _ in range(50):
            if (await current(services, product.id)).cutout != PENDING:
                break
            await asyncio.sleep(0.1)
    cut = (await current(services, product.id)).cutout
    assert cut is not None and (cut.model, cut.status, cut.error) == ('sim', 'done', None)
    assert cut.url is not None and cut.url.startswith(f'/files/products/{product.id}/cutout-')
    alpha = np.asarray(Image.open(services.settings.data_dir / cut.url.removeprefix('/files/')))[:, :, 3]
    assert (alpha[0, 0], alpha[30, 20]) == (0, 255)
    assert [w.concurrency for w in build_workers(services, queues)] == [1, 2, 1]


async def test_cutout_reports_missing_and_unreadable_photos(services: Services) -> None:
    missing = await photo_product(services, '/files/uploads/gone.jpg')
    broken = await photo_product(services, write_upload(services, 'broken.jpg', b'not an image'))
    for product in (missing, broken):
        assert isinstance(product.photo, FilePhoto)
        await cutout(services, product.id, product.photo.url)
    assert (await current(services, missing.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='找不到商品照：/files/uploads/gone.jpg'
    )
    assert (await current(services, broken.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='照片無法讀取'
    )


async def test_cutout_reads_local_photos_by_their_quoted_url(services: Services) -> None:
    folder = services.settings.local_photos_dir
    folder.mkdir(parents=True)
    (folder / '精華液 30ml.jpg').write_bytes(photo_bytes())
    product = await photo_product(services, f'/files/local/{quote("精華液 30ml.jpg", safe="")}', source='local')
    assert isinstance(product.photo, FilePhoto)
    await cutout(services, product.id, product.photo.url)
    cut = (await current(services, product.id)).cutout
    assert cut is not None and cut.status == 'done'


async def test_cutout_discards_its_result_when_the_photo_changed_meanwhile(services: Services) -> None:
    old_url = write_upload(services, 'old.jpg', photo_bytes())
    product = await photo_product(services, old_url)
    newer = ProductCutout(model='sim', status='done', url='/files/products/x/cutout-newer.png', error=None)

    class PhotoChangedWhileWaiting(CutoutEngine):
        async def segmenter(self) -> Segmenter:
            # 等模型時，使用者換了照片，新照片的去背也已經完成
            fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
            changed = {**fields, 'photo': {'source': 'upload', 'url': '/files/uploads/new.jpg'}}
            async with services.db.session() as s:
                await catalog.save_product(s, ProductDraft.model_validate({**changed, 'cutout': newer.to_json()}), NOW)
            return SimSegmenter()

    services.cutouts = PhotoChangedWhileWaiting('sim', services.settings.data_dir, services.redis)
    folder = services.settings.data_dir / 'products' / product.id
    folder.mkdir(parents=True)
    (folder / 'cutout-newer.png').write_bytes(b'newer')
    await cutout(services, product.id, old_url)
    assert (await current(services, product.id)).cutout == newer
    # 舊照片的結果丟掉，新照片的檔案留著
    assert [f.name for f in folder.iterdir()] == ['cutout-newer.png']
    # 照片早已換掉的任務直接結束
    await cutout(services, product.id, old_url)
    assert (await current(services, product.id)).cutout == newer


async def test_recovery_releases_cutout_orphans_and_requeues_pending_cutouts(
    services: Services, queues: Queues
) -> None:
    product = await photo_product(services, write_upload(services, 'a.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    key = cutout_key(product.id, product.photo.url)
    await queues.enqueue_cutout(product.id, product.photo.url)
    taken = await queues.cutouts.dequeue(timeout=1)
    assert taken is not None and taken.key == key
    await taken.update(status=Status.ACTIVE)
    await recover(services, queues)
    record = await queues.cutouts.job(key)
    assert record is not None and record.status == Status.QUEUED
    assert await queues.cutouts.count('active') == 0


async def test_pending_cutouts_whose_job_was_lost_are_requeued_once(services: Services, queues: Queues) -> None:
    """佇列裡沒有紀錄（寫入佇列時出錯、紀錄被清掉）的去背中商品要重新排入；已在佇列裡的不會重複排入。"""
    product = await photo_product(services, write_upload(services, 'lost.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    assert await queues.cutouts.count('queued') == 0
    assert await requeue_pending_cutouts(services, queues) == 1
    record = await queues.cutouts.job(cutout_key(product.id, product.photo.url))
    assert record is not None and record.status == Status.QUEUED
    # 第二次：工作還在佇列裡，SAQ 以 key 去重，不會再多一筆
    assert await requeue_pending_cutouts(services, queues) == 0
    assert await queues.cutouts.count('queued') == 1


async def test_the_requeue_loop_keeps_going_after_an_error(
    services: Services, queues: Queues, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    product = await photo_product(services, write_upload(services, 'lost.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    calls = 0

    async def flaky(services: Services, queues: Queues) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('redis 暫時連不上')
        return await requeue_pending_cutouts(services, queues)

    monkeypatch.setattr('app.worker.requeue_pending_cutouts', flaky)
    with caplog.at_level('WARNING', logger='app.worker'):
        loop = asyncio.create_task(requeue_cutouts_periodically(services, queues, interval=0.05))
        try:
            for _ in range(100):
                if await queues.cutouts.count('queued'):
                    break
                await asyncio.sleep(0.05)
        finally:
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)
    assert calls >= 2
    assert await queues.cutouts.count('queued') == 1
    assert 'redis 暫時連不上' in caplog.text
    assert loop.cancelled()


async def test_enqueued_cutouts_have_no_queue_timeout(queues: Queues) -> None:
    """第一次下載模型可能很久：佇列不設逾時，推論另有自己的逾時。"""
    await queues.enqueue_cutout('prod_x', '/files/uploads/a.jpg')
    record = await queues.cutouts.job(cutout_key('prod_x', '/files/uploads/a.jpg'))
    assert record is not None and record.timeout == 0


class StuckSegmenter:
    """推論卡住：直到 release（或最多 1 秒）才返回。"""

    name = 'stuck'

    def __init__(self) -> None:
        self.release = threading.Event()

    def cut(self, photo: bytes) -> bytes:
        self.release.wait(1)
        return photo


class FailingSegmenter:
    name = 'failing'

    def cut(self, photo: bytes) -> bytes:
        raise RuntimeError('boom')


def engine_returning(services: Services, segmenter: Segmenter) -> CutoutEngine:
    """永遠回傳指定 Segmenter 的引擎（不經過模型準備）。"""

    class FixedEngine(CutoutEngine):
        async def segmenter(self) -> Segmenter:
            return segmenter

    return FixedEngine('sim', services.settings.data_dir / 'models', services.redis)


def cutout_files(services: Services, product_id: str) -> list[str]:
    folder = services.settings.data_dir / 'products' / product_id
    return sorted(f.name for f in folder.glob('cutout-*.png'))


async def test_cutout_fails_when_the_inference_times_out(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('app.worker.CUTOUT_INFERENCE_TIMEOUT', 0.2)
    product = await photo_product(services, write_upload(services, 'slow.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    stuck = StuckSegmenter()
    services.cutouts = engine_returning(services, stuck)
    try:
        await cutout(services, product.id, product.photo.url)
    finally:
        stuck.release.set()
    assert (await current(services, product.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='去背逾時（超過 5 分鐘），請重試'
    )
    assert cutout_files(services, product.id) == []


async def test_cutout_reports_unexpected_errors_with_a_prefix_and_leaves_no_file(services: Services) -> None:
    product = await photo_product(services, write_upload(services, 'a.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    services.cutouts = engine_returning(services, FailingSegmenter())
    await cutout(services, product.id, product.photo.url)
    assert (await current(services, product.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='去背失敗：RuntimeError: boom'
    )
    assert cutout_files(services, product.id) == []


async def test_cutout_removes_its_own_file_when_writing_it_fails(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = await photo_product(services, write_upload(services, 'a.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    original = Path.write_bytes

    def half_write(self: Path, data: bytes) -> int:
        if not self.name.startswith('cutout-'):
            return original(self, data)
        original(self, data[:10])
        raise OSError('disk full')

    monkeypatch.setattr(Path, 'write_bytes', half_write)
    await cutout(services, product.id, product.photo.url)
    assert (await current(services, product.id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error='去背失敗：OSError: disk full'
    )
    assert cutout_files(services, product.id) == []


async def test_cutout_keeps_only_the_new_file_after_a_success(services: Services) -> None:
    product = await photo_product(services, write_upload(services, 'a.jpg', photo_bytes()))
    assert isinstance(product.photo, FilePhoto)
    folder = services.settings.data_dir / 'products' / product.id
    folder.mkdir(parents=True)
    (folder / 'cutout-old.png').write_bytes(b'old')
    await cutout(services, product.id, product.photo.url)
    cut = (await current(services, product.id)).cutout
    assert cut is not None and cut.url is not None and cut.status == 'done'
    assert cutout_files(services, product.id) == [cut.url.rsplit('/', 1)[1]]


@pytest.mark.parametrize('bad_id', ['..', 'a b', 'x' * 65])
async def test_cutout_refuses_product_ids_that_are_not_safe_folder_names(services: Services, bad_id: str) -> None:
    url = write_upload(services, 'a.jpg', photo_bytes())
    await photo_product(services, url, product_id=bad_id)
    await cutout(services, bad_id, url)
    assert (await current(services, bad_id)).cutout == ProductCutout(
        model='sim', status='failed', url=None, error=f'商品 id 格式錯誤：{bad_id}'
    )
    # 什麼都沒寫：data/ 底下沒有去背圖，也沒有建立 products 資料夾
    assert list(services.settings.data_dir.rglob('cutout-*.png')) == []
    assert not (services.settings.data_dir / 'products').exists()


async def test_run_task_returns_unfinished_when_the_wait_runs_out(queues: Queues) -> None:
    """沒有 worker 時，等不到結果要回傳 completed=False，不能丟出逾時例外。"""
    loop = asyncio.get_running_loop()
    started = loop.time()
    done = await queues.run_task('write_back', wait=0.5, history_id='hist_x')
    assert (done.completed, done.result) == (False, None)
    assert loop.time() - started < 1.5


@pytest.mark.parametrize(('mode', 'retriever'), [('bge', BgeRetriever), ('sim', SimRetriever)])
async def test_build_services_picks_the_retriever_by_rag_mode(
    mode: RagMode, retriever: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'app.worker.settings',
        Settings(_env_file=None, image_mode='sim', agent_mode='sim', brands_dir=BRANDS_DIR, rag_mode=mode),
    )
    built = build_services()
    try:
        assert isinstance(built.ports.retriever, retriever)
        assert built.rag.mode == mode
        if isinstance(built.ports.retriever, BgeRetriever):
            assert built.ports.retriever.engine is built.rag
            assert built.ports.retriever.store is built.vectors
            assert built.ports.retriever.locks is built.locks
    finally:
        await built.composer.aclose()
        await built.redis.aclose()
        await built.db.dispose()


@pytest.mark.parametrize(
    ('mode', 'posters', 'reviewer'),
    [('composer', ComposerPosters, ComposerReviewer), ('sim', SimPosters, SimReviewer)],
)
async def test_build_services_picks_the_posters_and_the_reviewer_by_review_mode(
    mode: ReviewMode, posters: type, reviewer: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'app.worker.settings',
        Settings(_env_file=None, image_mode='sim', agent_mode='sim', brands_dir=BRANDS_DIR, review_mode=mode),
    )
    built = build_services()
    try:
        assert isinstance(built.ports.posters, posters)
        assert isinstance(built.ports.reviewer, reviewer)
        if isinstance(built.ports.posters, ComposerPosters):
            # 審查用海報寫到 worker 設定的 data/，與 /files 讀取的是同一個資料夾
            assert built.ports.posters.composer is built.composer
            assert built.ports.posters.settings is built.settings
    finally:
        await built.composer.aclose()
        await built.redis.aclose()
        await built.db.dispose()


async def test_build_services_uses_gemini_for_the_agent_and_the_review_when_agent_mode_is_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gemini = Settings(
        _env_file=None,
        image_mode='sim',
        agent_mode='gemini',
        gemini_api_key='AIza-test-key-0000',
        brands_dir=BRANDS_DIR,
    )
    monkeypatch.setattr('app.worker.settings', gemini)
    built = build_services()
    try:
        assert isinstance(built.ports.agent, GeminiAgent)
        assert isinstance(built.ports.reviewer, GeminiReviewer)
        assert isinstance(built.ports.posters, ComposerPosters)
        assert isinstance(built.gemini, GeminiClient) and built.gemini.configured
        assert built.ports.usage is not None
    finally:
        assert built.gemini is not None
        await built.gemini.aclose()
        await built.composer.aclose()
        await built.redis.aclose()
        await built.db.dispose()


def test_review_mode_defaults_to_the_composer() -> None:
    assert Settings(_env_file=None).review_mode == 'composer'


class StateRecorder:
    def __init__(self) -> None:
        self.states: list[object] = []

    async def __call__(self, message: dict[str, object]) -> None:
        self.states.append(message['state'])


async def test_rag_warm_up_checks_the_files_then_syncs_every_brand(
    services: Services, chroma: VectorStore, redis: Redis
) -> None:
    encoder, recorder = FakeEncoder(), StateRecorder()
    services.rag = RagEngine('bge', Path('models'), redis, models=[], load=lambda _: encoder, on_state=recorder)
    services.vectors = chroma
    await warm_up_rag(services)
    # 先回報 standby（模型檔已核對）；同步需要向量化時才載入
    assert recorder.states == ['standby', 'loading', 'ready']
    assert await chroma.brands() == ['misty-isle', 'selune']
    async with services.db.session() as s:
        assert len(await chroma.metadata('selune')) == len(await catalog.list_chunks(s, 'selune'))


async def test_rag_warm_up_in_sim_mode_only_reports_the_state(services: Services, redis: Redis) -> None:
    services.vectors = VectorStore('http://127.0.0.1:9')
    await warm_up_rag(services)
    raw = await redis.get('rag:model')
    assert raw is not None and json.loads(raw) == {'model': 'sim', 'state': 'sim', 'error': None}


async def test_rag_warm_up_logs_errors_without_raising(
    services: Services, redis: Redis, caplog: pytest.LogCaptureFixture
) -> None:
    services.rag = RagEngine('bge', Path('models'), redis, models=[], load=lambda _: FakeEncoder())
    services.vectors = VectorStore('http://127.0.0.1:9')
    with caplog.at_level('ERROR', logger='app.worker'):
        await warm_up_rag(services)
    assert 'RAG 模型準備或品牌同步失敗' in caplog.text
    assert '向量庫（Chroma）無法連線' in caplog.text


async def collect_ingest(
    services: Services, task_id: str, name: str, text: str, brand_id: str = 'misty-isle'
) -> list[dict[str, Any]]:
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel(task_id))
    await ingest(services, task_id, brand_id, name, text)
    return await read_ingest(pubsub)


async def read_ingest(pubsub: PubSub) -> list[dict[str, Any]]:
    """讀到 ingest.stored 或錯誤為止（最多約 10 秒），再關閉 pubsub。"""
    messages: list[dict[str, Any]] = []
    for _ in range(50):
        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if raw is None:
            continue
        messages.append(json.loads(raw['data']))
        if 'error' in messages[-1] or messages[-1]['type'] == 'ingest.stored':
            break
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    return messages


DOC = '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo\n\n2026 春季素材 CTR 3.9%。'
STORED = {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 3}


async def uploads(services: Services, brand_id: str = 'misty-isle') -> list[RagChunk]:
    async with services.db.session() as s:
        return [c for c, origin in await catalog.list_chunks(s, brand_id) if origin == 'upload']


def embedded(chunks: list[RagChunk], previews: list[list[float]]) -> list[dict[str, Any]]:
    return [
        IngestEmbeddedEvent(
            type='ingest.embedded', chunk_id=c.id, index=i, total=len(chunks), dims=EMBED_DIMS, preview=p
        ).to_json()
        for i, (c, p) in enumerate(zip(chunks, previews, strict=True))
    ]


@pytest.fixture
def bge(services: Services, redis: Redis, chroma: VectorStore) -> FakeEncoder:
    """真實版的上傳：FakeEncoder 與 Chroma 的 genai_test database。"""
    encoder = FakeEncoder()
    services.rag = fake_engine(redis, encoder)
    services.vectors = chroma
    return encoder


async def test_sim_ingest_chunks_in_python_with_simulated_vectors(services: Services) -> None:
    messages = await collect_ingest(services, 't1', 'ci_update.md', DOC)
    chunks = chunk_document('misty-isle', 'ci_update.md', DOC)
    assert len(chunks) == 3
    assert messages == [
        IngestChunkedEvent(type='ingest.chunked', source='ci_update.md', chunks=chunks).to_json(),
        *embedded(chunks, [embed_preview(c.text) for c in chunks]),
        STORED,
    ]
    assert await uploads(services) == chunks


async def test_bge_ingest_embeds_each_chunk_then_writes_postgres_and_chroma(
    services: Services, bge: FakeEncoder, chroma: VectorStore
) -> None:
    messages = await collect_ingest(services, 't1', 'ci_update.md', DOC)
    chunks = chunk_document('misty-isle', 'ci_update.md', DOC)
    # 逐塊向量化「章節：內文」；進度是真實向量的前 6 維（四捨五入到小數 3 位）
    assert bge.embedded == [index_text(c) for c in chunks]
    previews = [vector_preview(FakeEncoder.vector(index_text(c))) for c in chunks]
    assert messages == [
        IngestChunkedEvent(type='ingest.chunked', source='ci_update.md', chunks=chunks).to_json(),
        *embedded(chunks, previews),
        STORED,
    ]
    assert await uploads(services) == chunks
    assert await chroma.metadata('misty-isle') == {c.id: chunk_metadata('misty-isle', c, 'upload') for c in chunks}

    # 同名文件重新上傳時取代舊的切塊（切塊變少時，多的要刪掉）；其他文件不受影響
    other = '# 字型\n標題使用 Noto Serif TC。'
    shorter = '# 色彩更新\n主色改為 #1F3A34。'
    await collect_ingest(services, 't2', 'other.md', other)
    assert (await collect_ingest(services, 't3', 'ci_update.md', shorter))[-1]['type'] == 'ingest.stored'
    expected = chunk_document('misty-isle', 'other.md', other) + chunk_document('misty-isle', 'ci_update.md', shorter)
    assert await uploads(services) == expected
    assert await chroma.metadata('misty-isle') == {c.id: chunk_metadata('misty-isle', c, 'upload') for c in expected}


async def test_bge_ingest_embeds_outside_the_brand_lock_but_writes_inside_it(
    services: Services, bge: FakeEncoder
) -> None:
    async with services.locks('misty-isle'):
        task = asyncio.create_task(collect_ingest(services, 't1', 'ci_update.md', DOC))
        for _ in range(50):
            if len(bge.embedded) == 3:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        assert len(bge.embedded) == 3
        assert await uploads(services) == []
        assert not task.done()
    assert (await task)[-1] == STORED
    assert len(await uploads(services)) == 3


async def test_ingest_reports_a_missing_brand_and_an_empty_document(services: Services) -> None:
    assert await collect_ingest(services, 't1', 'a.md', '主色', brand_id='nope') == [
        {'error': {'code': 'not_found', 'message': '找不到品牌：nope'}}
    ]
    assert await collect_ingest(services, 't2', 'empty.md', '   ') == [
        {'error': {'code': 'invalid', 'message': '文件沒有可用的文字內容'}}
    ]


async def test_bge_ingest_reports_an_unreachable_chroma_as_unavailable_and_keeps_postgres(
    services: Services, bge: FakeEncoder
) -> None:
    services.vectors = VectorStore('http://127.0.0.1:9')
    messages = await collect_ingest(services, 't1', 'ci_update.md', DOC)
    assert [m.get('type') for m in messages[:-1]] == ['ingest.chunked'] + ['ingest.embedded'] * 3
    error = messages[-1]['error']
    assert error['code'] == 'unavailable'
    assert error['message'].startswith('向量庫（Chroma）無法連線（http://127.0.0.1:9）：')
    # PostgreSQL 為準：下一次同步會補上 Chroma
    assert len(await uploads(services)) == 3


async def test_bge_ingest_reports_a_model_failure_as_unavailable(
    services: Services, redis: Redis, chroma: VectorStore
) -> None:
    def broken(models_dir: Path) -> FakeEncoder:
        raise RuntimeError('模型檔損毀')

    services.rag = RagEngine('bge', Path('models'), redis, models=[], load=broken)
    services.vectors = chroma
    messages = await collect_ingest(services, 't1', 'ci_update.md', DOC)
    assert [m.get('type') for m in messages[:-1]] == ['ingest.chunked']
    assert messages[-1] == {'error': {'code': 'unavailable', 'message': 'RAG 模型準備失敗：模型檔損毀'}}
    assert await uploads(services) == []


async def test_ingest_reports_unexpected_errors_as_internal(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(brand_id: str, name: str, text: str) -> list[RagChunk]:
        raise RuntimeError('boom')

    monkeypatch.setattr('app.worker.chunk_document', boom)
    assert await collect_ingest(services, 't1', 'a.md', '主色') == [
        {'error': {'code': 'internal', 'message': '文件處理失敗：RuntimeError: boom'}}
    ]


def stuck_embedding(services: Services, redis: Redis, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """真實版的上傳停在第一塊的向量化（不會結束）；回傳開始向量化時設定的 event。"""
    services.rag = fake_engine(redis, FakeEncoder())
    embedding = asyncio.Event()

    async def stuck(text: str) -> list[float]:
        embedding.set()
        await asyncio.Event().wait()
        raise AssertionError('向量化不會結束')

    monkeypatch.setattr(services.rag, 'embed', stuck)
    return embedding


async def test_a_cancelled_ingest_publishes_an_error_then_stays_cancelled(
    services: Services, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SAQ 的任務逾時（TASK_TIMEOUT）會取消 ingest：先發布錯誤（api 不必等閒置逾時），再讓 SAQ 照樣看到取消。"""
    embedding = stuck_embedding(services, redis, monkeypatch)
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel('t1'))
    task = asyncio.create_task(ingest(services, 't1', 'misty-isle', 'ci_update.md', DOC))
    await embedding.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    messages = await read_ingest(pubsub)
    assert [m.get('type') for m in messages] == ['ingest.chunked', None]
    message = '文件處理超過 10 分鐘而中止，請把文件分成幾份再上傳'
    assert messages[-1] == {'error': {'code': 'unavailable', 'message': message}}


async def test_a_cancelled_ingest_stays_cancelled_when_publishing_the_error_fails(
    services: Services, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedding = stuck_embedding(services, redis, monkeypatch)
    published: list[str] = []

    async def publish(channel: str, message: str) -> int:
        if 'error' in json.loads(message):
            raise ConnectionError('Redis 已停止')
        published.append(message)
        return 0

    monkeypatch.setattr(services.redis, 'publish', publish)
    task = asyncio.create_task(ingest(services, 't1', 'misty-isle', 'ci_update.md', DOC))
    await embedding.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [json.loads(m)['type'] for m in published] == ['ingest.chunked']


async def selected(services: Services) -> HistoryEntry:
    """寫入歷史紀錄（選定 selune-retry 的 IG 貼文）；history 參照 jobs，所以先建立任務。"""
    entry = selected_history()
    async with services.db.session() as s:
        await jobs.create_job(s, entry.job_id, entry.input, NOW)
        await history.add_history(s, entry)
    return entry


async def chunks_by_origin(services: Services, brand_id: str = 'selune') -> list[tuple[str, str]]:
    async with services.db.session() as s:
        return [(c.id, origin) for c, origin in await catalog.list_chunks(s, brand_id)]


async def history_chunks(services: Services) -> list[RagChunk]:
    async with services.db.session() as s:
        return [c for c, origin in await catalog.list_chunks(s, 'selune') if origin == 'history']


async def written(services: Services, history_id: str) -> bool:
    async with services.db.session() as s:
        entry = await history.get_history(s, history_id)
    assert entry is not None
    return entry.written_to_rag


async def test_sim_write_back_upserts_the_history_chunk_into_postgres_only(
    services: Services, chroma: VectorStore
) -> None:
    services.vectors = chroma
    entry = await selected(services)
    chunk = history_chunk(entry, '極光玻尿酸修護精華 30ml', ZoneInfo('Asia/Taipei'))
    assert await write_back(services, entry.id) is True
    assert await history_chunks(services) == [chunk]
    assert await written(services, entry.id) is True
    # 列在知識庫的最後（設定檔、合規替代用語、上傳的手冊之後）；重跑以 id upsert，不會重複
    assert await write_back(services, entry.id) is True
    assert (await chunks_by_origin(services))[-1] == (chunk.id, 'history')
    assert await history_chunks(services) == [chunk]
    # 模擬模式不連 Chroma
    assert await chroma.brands() == []
    assert await write_back(services, 'hist_nope') is False


async def test_write_back_leaves_out_the_name_of_a_deleted_product(services: Services) -> None:
    entry = await selected(services)
    async with services.db.session() as s:
        assert await catalog.delete_product(s, entry.product_id)
    assert await write_back(services, entry.id) is True
    [chunk] = await history_chunks(services)
    assert chunk == history_chunk(entry, None, ZoneInfo('Asia/Taipei'))
    assert chunk.text.startswith('IG 貼文海報，審查 99 分。')


async def test_bge_write_back_embeds_the_chunk_into_chroma_where_retrieval_finds_it(
    services: Services, bge: FakeEncoder, chroma: VectorStore
) -> None:
    entry = await selected(services)
    await sync_brand(services.db, chroma, services.rag, services.locks, 'selune')
    bge.embedded.clear()
    chunk = history_chunk(entry, '極光玻尿酸修護精華 30ml', ZoneInfo('Asia/Taipei'))
    assert await write_back(services, entry.id) is True
    assert bge.embedded == [index_text(chunk)]
    assert (await chroma.metadata('selune'))[chunk.id] == chunk_metadata('selune', chunk, 'history')
    assert await history_chunks(services) == [chunk]
    assert await written(services, entry.id) is True
    # 寫入的內容與同步要的相同：之後的同步不必重新向量化
    assert await sync_brand(services.db, chroma, services.rag, services.locks, 'selune') == SyncResult(0, 0)
    assert len(bge.embedded) == 1
    hits = await chroma.query('selune', FakeEncoder.vector(index_text(chunk)), 1)
    assert [h.id for h in hits] == [chunk.id]


async def test_bge_write_back_writes_postgres_and_embeds_outside_the_brand_lock(
    services: Services, bge: FakeEncoder, chroma: VectorStore
) -> None:
    entry = await selected(services)
    async with services.locks('selune'):
        task = asyncio.create_task(write_back(services, entry.id))
        for _ in range(50):
            if bge.embedded:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        assert len(bge.embedded) == 1
        assert len(await history_chunks(services)) == 1
        assert not task.done()
        assert await chroma.metadata('selune') == {}
    assert await task is True
    assert list(await chroma.metadata('selune')) == [f'selune#hist-{entry.id}']


async def test_bge_write_back_fails_when_chroma_is_down_but_keeps_postgres(
    services: Services, bge: FakeEncoder
) -> None:
    services.vectors = VectorStore('http://127.0.0.1:9')
    entry = await selected(services)
    with pytest.raises(Unavailable, match=r'^向量庫（Chroma）無法連線'):
        await write_back(services, entry.id)
    # PostgreSQL 為準：下一次同步會補上 Chroma；writtenToRag 維持 false
    assert len(await history_chunks(services)) == 1
    assert await written(services, entry.id) is False


async def test_run_task_raises_task_failed_when_the_task_fails_or_is_aborted(
    services: Services, queues: Queues, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(services: Services, history_id: str) -> bool:
        raise RuntimeError('boom')

    monkeypatch.setattr('app.worker.write_back', broken)
    async with running(services, queues):
        with pytest.raises(TaskFailed, match='背景工作 write_back 失敗'):
            await queues.run_task('write_back', wait=5, history_id='hist_x')
    # 沒有 worker：排隊中的工作被中止
    waiting = asyncio.create_task(queues.run_task('write_back', wait=5, history_id='hist_y'))
    for _ in range(50):
        queued = [job async for job in queues.tasks.iter_jobs(statuses=[Status.QUEUED])]
        if queued:
            break
        await asyncio.sleep(0.05)
    await queues.tasks.abort(queued[0], 'stop')
    with pytest.raises(TaskFailed, match='stop'):
        await waiting
