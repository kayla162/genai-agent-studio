"""worker：任務經過佇列執行、啟動時復原、去背、品牌文件上傳、回寫。需要 composer。"""

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

import numpy as np
import pytest
from PIL import Image
from redis.asyncio import Redis
from saq.job import Status

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import (
    FilePhoto,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    Price,
    Product,
    ProductCutout,
    ProductDraft,
)
from app.cutout.engine import CutoutEngine
from app.cutout.segmenter import Segmenter, SimSegmenter
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues, cutout_key, ingest_channel
from app.repo import catalog, jobs
from app.settings import Settings
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str, tmp_path: Path) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    settings = Settings(data_dir=tmp_path / 'data', local_photos_dir=tmp_path / 'local')
    cutouts = CutoutEngine('sim', tmp_path / 'models', redis)
    yield Services(db, redis, EventStore(db, redis), composer, ports, speed=0, settings=settings, cutouts=cutouts)
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


async def collect_ingest(services: Services, task_id: str, name: str, text: str) -> list[dict[str, Any]]:
    pubsub = services.redis.pubsub()
    await pubsub.subscribe(ingest_channel(task_id))
    await ingest(services, task_id, 'misty-isle', name, text)
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


async def test_ingest_reports_each_step_and_stores_the_chunks(services: Services) -> None:
    text = '# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo\n\n2026 春季素材 CTR 3.9%。'
    messages = await collect_ingest(services, 't1', 'ci_update.md', text)
    assert [m['type'] for m in messages] == ['ingest.chunked'] + ['ingest.embedded'] * 3 + ['ingest.stored']
    assert messages[-1] == {'type': 'ingest.stored', 'collection': 'misty-isle_ci', 'count': 3}
    async with services.db.session() as s:
        brand = await catalog.get_brand(s, 'misty-isle')
    assert brand is not None
    assert [c.source for c in brand.guideline_chunks].count('ci_update.md') == 3
    assert await collect_ingest(services, 't2', 'empty.md', '   ') == [
        {'error': {'code': 'invalid', 'message': '文件沒有可用的文字內容'}}
    ]
