"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：ingest（品牌手冊上傳：切塊、向量化、寫入知識庫）、write_back（選定的海報回寫成歷史切塊），最多同時兩個
- cutouts 佇列：cutout（商品照去背，一次一個）
- 啟動時在背景準備模型：去背模型下載並載入；RAG 模型下載並核對，再把品牌同步到 Chroma
  （同步發現索引有差異時就載入 RAG 模型；沒有差異時，第一次檢索才載入）
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務與去背中的商品重新放回佇列；
  去背中的商品在執行期間也會定時補排（寫入佇列時出錯、紀錄遺失的商品不會一直卡在去背中）
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from itertools import batched
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from saq import Worker
from saq.types import Context
from sqlalchemy import select

from app.adapters.composer import ComposerClient
from app.contract import (
    FilePhoto,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
    JobFailedEvent,
    JobStatusEvent,
    LogEvent,
    ProductCutout,
    RagChunk,
)
from app.core.clock import utc_now
from app.cutout.engine import CutoutEngine
from app.cutout.processing import CutoutError
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError, Invalid, NotFound
from app.events import EventStore
from app.files import photo_path, product_folder
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import TASK_TIMEOUT, Queues, ingest_channel
from app.rag.chunking import EMBED_DIMS, chunk_document, embed_preview, vector_preview
from app.rag.engine import RagEngine
from app.rag.history import history_chunk
from app.rag.retriever import BgeRetriever
from app.rag.store import VectorRecord, VectorStore, collection_name
from app.rag.sync import UPSERT_BATCH, BrandLocks, sync_all, vector_record
from app.repo import catalog, history
from app.settings import Settings, settings

logger = logging.getLogger(__name__)

RESTART_REASON = 'worker 重新啟動，任務中斷'
#: 單張照片推論的逾時（秒）；等模型準備（含第一次下載）不算在內
CUTOUT_INFERENCE_TIMEOUT = 300
#: 定時把「去背中卻不在佇列裡」的商品重新排入的間隔（秒）：寫入資料庫或佇列時出錯會留下這樣的商品，
#: 卡片上的按鈕在去背中是停用的，不補排的話會一直顯示去背中
CUTOUT_REQUEUE_INTERVAL = 120
#: 去背推論專用的單一執行緒。逾時的推論會繼續在它的執行緒裡跑完（執行緒無法中途取消），
#: 單一執行緒確保下一張一定等它結束才開始，不會有兩個推論同時執行（每個約 8 GB 記憶體，Docker 實測尖峰約 7.6 GiB）。
INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cutout')


@dataclass
class Services:
    db: Database
    redis: Redis
    store: EventStore
    composer: ComposerClient
    ports: Ports
    #: 模擬模式的播放速度（0 為不等待）
    speed: float
    settings: Settings
    cutouts: CutoutEngine
    #: RAG 模型；模式（bge／sim）以它為準
    rag: RagEngine
    #: Chroma（模擬模式不使用，也不會連線）
    vectors: VectorStore
    #: 寫入 Chroma 前要取得的品牌鎖（同步、上傳、回寫共用）
    locks: BrandLocks = field(default_factory=BrandLocks)

    async def pace(self, ms: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms / 1000 / self.speed)


def build_services() -> Services:
    """RAG_MODE=bge 時檢索換成 BgeRetriever；Agent、生圖與審查仍是模擬版（Plan 6、7 換成真實版）。"""
    db = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    composer = ComposerClient(settings.composer_url)
    rag = RagEngine(settings.rag_mode, settings.models_dir, redis)
    vectors = VectorStore(settings.chroma_url)
    locks = BrandLocks()
    ports = sim_ports(
        composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
    )
    if settings.rag_mode == 'bge':
        ports = replace(ports, retriever=BgeRetriever(db, vectors, rag, locks))
    cutouts = CutoutEngine(settings.cutout_model, settings.models_dir, redis)
    store = EventStore(db, redis)
    return Services(db, redis, store, composer, ports, settings.sim_speed, settings, cutouts, rag, vectors, locks)


async def warm_up_rag(services: Services) -> None:
    """worker 啟動時在背景：下載並核對 RAG 模型檔（不載入），再依序同步所有品牌到 Chroma。
    失敗只記錄（模型狀態已寫到 Redis），檢索與上傳時會再試；模擬模式只回報狀態。"""
    try:
        await services.rag.prepare_files()
        if services.rag.mode == 'bge':
            await sync_all(services.db, services.vectors, services.rag, services.locks)
    except Exception:
        logger.exception('RAG 模型準備或品牌同步失敗')


async def cutout(services: Services, product_id: str, photo_url: str) -> None:
    """去背：讀照片 → 等模型（不限時間）→ 推論（專用執行緒，有逾時）→ 寫入 PNG → 確認商品沒變才寫入結果。"""
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    # 商品已刪除，或照片已經換掉（較新的任務會處理新照片）
    if product is None or not isinstance(product.photo, FilePhoto) or product.photo.url != photo_url:
        return
    written: Path | None = None
    try:
        folder = product_folder(services.settings, product_id)
        photo = await asyncio.to_thread(photo_path(services.settings, photo_url).read_bytes)
        segmenter = await services.cutouts.segmenter()
        try:
            async with asyncio.timeout(CUTOUT_INFERENCE_TIMEOUT):
                png = await asyncio.get_running_loop().run_in_executor(INFERENCE_EXECUTOR, segmenter.cut, photo)
        except TimeoutError as error:
            raise CutoutError('去背逾時（超過 5 分鐘），請重試') from error
        name = f'cutout-{hashlib.sha256(png).hexdigest()[:12]}.png'
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        written = folder / name
        await asyncio.to_thread(written.write_bytes, png)
        result = ProductCutout(
            model=segmenter.name, status='done', url=f'/files/products/{product_id}/{name}', error=None
        )
    except Exception as error:  # noqa: BLE001 - 任何錯誤都顯示在商品卡上
        logger.exception('去背失敗：product_id=%s', product_id)
        reason = failure_reason(error) if isinstance(error, AppError) else f'去背失敗：{failure_reason(error)}'
        result = ProductCutout(model=services.cutouts.model, status='failed', url=None, error=reason)
    async with services.db.session() as s:
        saved = await catalog.set_cutout(s, product_id, photo_url, result)
    if written is not None:
        await asyncio.to_thread(_remove_cutouts, written, keep_written=result.status == 'done' and saved is not None)


def _remove_cutouts(written: Path, *, keep_written: bool) -> None:
    """結果寫入資料庫後，刪掉同一商品的舊去背圖；結果沒寫入（失敗、商品已刪除或換了照片）時只刪掉這次寫的檔案。"""
    targets = [f for f in written.parent.glob('cutout-*.png') if f != written] if keep_written else [written]
    for f in targets:
        f.unlink(missing_ok=True)


#: 上傳進度的訊息（一則 IngestEvent 或 { error }）發布到 ingest:{task_id}
Send = Callable[[dict[str, Any]], Awaitable[None]]
#: 上傳超過任務時限（TASK_TIMEOUT）被 SAQ 取消時的訊息
INGEST_CANCELLED = f'文件處理超過 {TASK_TIMEOUT // 60} 分鐘而中止，請把文件分成幾份再上傳'


async def ingest(services: Services, task_id: str, brand_id: str, name: str, text: str) -> None:
    """品牌手冊：切塊 → 向量化 → 寫入知識庫；每一步發布到 Redis 頻道 ingest:{task_id}，api 以 NDJSON 串流轉給前端。

    錯誤碼：品牌不存在 not_found、沒有可用文字 invalid、模型準備失敗或 Chroma 無法連線 unavailable、
    超過任務時限被取消 unavailable（發布後仍把取消丟給 SAQ）、其他 internal。
    """

    async def send(message: dict[str, Any]) -> None:
        await services.redis.publish(ingest_channel(task_id), json.dumps(message, ensure_ascii=False))

    try:
        async with services.db.session() as s:
            if await catalog.get_brand(s, brand_id) is None:
                raise NotFound(f'找不到品牌：{brand_id}')
        chunks = chunk_document(brand_id, name, text)
        if not chunks:
            raise Invalid('文件沒有可用的文字內容')
        embed_and_write = _ingest_bge if services.rag.mode == 'bge' else _ingest_sim
        await embed_and_write(services, brand_id, name, chunks, send)
        stored = IngestStoredEvent(type='ingest.stored', collection=collection_name(brand_id), count=len(chunks))
        await send(stored.to_json())
    except asyncio.CancelledError:
        # 超過任務時限時 SAQ 會取消這裡：先告訴前端（否則 api 要等到閒置逾時，訊息也不對），
        # 再把取消往外丟給 SAQ。發布失敗（例如 Redis 停止）也不能吞掉取消
        logger.warning('品牌文件上傳被取消：task_id=%s', task_id)
        with contextlib.suppress(Exception):
            await send({'error': {'code': 'unavailable', 'message': INGEST_CANCELLED}})
        raise
    except Exception as error:  # noqa: BLE001 - 錯誤一律轉給前端
        logger.exception('品牌文件上傳失敗：task_id=%s', task_id)
        if isinstance(error, AppError):
            await send({'error': {'code': error.code, 'message': error.message}})
        else:
            await send({'error': {'code': 'internal', 'message': f'文件處理失敗：{failure_reason(error)}'}})


def _embedded(chunks: list[RagChunk], i: int, dims: int, preview: list[float]) -> dict[str, Any]:
    event = IngestEmbeddedEvent(
        type='ingest.embedded', chunk_id=chunks[i].id, index=i, total=len(chunks), dims=dims, preview=preview
    )
    return event.to_json()


async def _ingest_bge(services: Services, brand_id: str, name: str, chunks: list[RagChunk], send: Send) -> None:
    """逐塊向量化（進度顯示真實向量的前 6 維）；完成後在品牌鎖內先寫 PostgreSQL，再寫 Chroma：
    先刪除同一個 source 的上傳切塊，再 upsert。Chroma 寫入失敗時 PostgreSQL 的資料仍在，下一次同步會補上。"""
    await send(IngestChunkedEvent(type='ingest.chunked', source=name, chunks=chunks).to_json())
    records: list[VectorRecord] = []
    for i, chunk in enumerate(chunks):
        record = await vector_record(services.rag, brand_id, chunk, 'upload')
        records.append(record)
        await send(_embedded(chunks, i, len(record.embedding), vector_preview(record.embedding)))
    async with services.locks(brand_id):
        async with services.db.session() as s:
            await catalog.replace_document_chunks(s, brand_id, name, chunks, utc_now())
        await services.vectors.delete(brand_id, where={'$and': [{'source': name}, {'origin': 'upload'}]})
        for batch in batched(records, UPSERT_BATCH, strict=False):
            await services.vectors.upsert(brand_id, batch)


async def _ingest_sim(services: Services, brand_id: str, name: str, chunks: list[RagChunk], send: Send) -> None:
    """模擬版：向量是雜湊產生的假數字，依 1× 時間軸等待；只寫入 PostgreSQL。"""
    await services.pace(400)
    await send(IngestChunkedEvent(type='ingest.chunked', source=name, chunks=chunks).to_json())
    for i, chunk in enumerate(chunks):
        await services.pace(250)
        await send(_embedded(chunks, i, EMBED_DIMS, embed_preview(chunk.text)))
    async with services.db.session() as s:
        await catalog.replace_document_chunks(s, brand_id, name, chunks, utc_now())
    await services.pace(300)


async def write_back(services: Services, history_id: str) -> bool:
    """選定的海報回寫成歷史切塊：以 id upsert 到 PostgreSQL（重跑不會重複），真實版再向量化並寫入 Chroma
    （向量化在品牌鎖之外，寫入在鎖內），最後標記 writtenToRag。歷史紀錄不存在時回傳 False。
    切塊文字帶有商品目前的名稱；商品已刪除時省略。

    出錯時丟出例外，SAQ 記為失敗，api 回傳 writtenToRag: false；已寫入 PostgreSQL 的切塊在下一次同步時補上 Chroma。
    """
    async with services.db.session() as s:
        entry = await history.get_history(s, history_id)
        product = await catalog.get_product(s, entry.product_id) if entry else None
    if entry is None:
        return False
    chunk = history_chunk(entry, product.name if product else None, ZoneInfo(services.settings.timezone))
    async with services.db.session() as s:
        await catalog.upsert_chunk(s, entry.brand_id, chunk, 'history', utc_now())
    if services.rag.mode == 'bge':
        record = await vector_record(services.rag, entry.brand_id, chunk, 'history')
        async with services.locks(entry.brand_id):
            await services.vectors.upsert(entry.brand_id, [record])
    async with services.db.session() as s:
        return await history.mark_written(s, history_id)


async def recover(services: Services, queues: Queues) -> None:
    # 前一個 worker 被強制終止時，佇列紀錄會停在執行中：不放掉的話，系統狀態永遠算它執行中，
    # 排隊中的任務也會因為 key 相同被當成重複而不再執行。任務在資料庫裡可能已經結束，所以不依資料庫的任務逐筆處理
    for key in await queues.release_orphans(RESTART_REASON):
        logger.warning('釋放前一個 worker 留下的佇列紀錄：%s', key)
    async with services.db.session() as s:
        rows = (await s.scalars(select(JobRow).where(JobRow.finished.is_(False)).order_by(JobRow.created_at))).all()
    for row in rows:
        if row.stage == 'queued':
            await queues.enqueue_job(row.id)
            continue
        await services.store.append(row.id, LogEvent(type='log', source='api', level='error', message=RESTART_REASON))
        await services.store.append(row.id, JobFailedEvent(type='job.failed', job_id=row.id, reason=RESTART_REASON))
        await services.store.append(row.id, JobStatusEvent(type='job.status', stage='failed', round=row.round))
    # 去背中斷的商品重新排入
    await requeue_pending_cutouts(services, queues)


async def requeue_pending_cutouts(services: Services, queues: Queues) -> int:
    """把還在去背中的商品排入 cutouts 佇列，回傳新排入的筆數。
    排入以商品與照片當 key，排隊中或執行中的工作會被 SAQ 去重，所以隨時可以呼叫。"""
    async with services.db.session() as s:
        pending = await catalog.pending_cutouts(s)
    requeued = 0
    for product in pending:
        if isinstance(product.photo, FilePhoto) and await queues.enqueue_cutout(product.id, product.photo.url):
            requeued += 1
    return requeued


async def requeue_cutouts_periodically(
    services: Services, queues: Queues, interval: float = CUTOUT_REQUEUE_INTERVAL
) -> None:
    """worker 執行期間定時補排：只在啟動時補排的話，執行中才遺失的工作要等到下次重新啟動。出錯只記錄，下一輪再試。"""
    while True:
        await asyncio.sleep(interval)
        try:
            requeued = await requeue_pending_cutouts(services, queues)
            if requeued:
                logger.warning('補排 %d 個不在佇列裡的去背中商品', requeued)
        except Exception:
            logger.exception('補排去背中商品失敗')


def build_workers(services: Services, queues: Queues, **options: Any) -> tuple[Worker[Context], ...]:
    async def run_job_fn(ctx: Context, *, job_id: str) -> None:
        await run_job(job_id, services.db, services.store, services.ports, speed=services.speed)

    async def cutout_fn(ctx: Context, *, product_id: str, photo_url: str) -> None:
        await cutout(services, product_id, photo_url)

    async def ingest_fn(ctx: Context, *, task_id: str, brand_id: str, name: str, text: str) -> None:
        await ingest(services, task_id, brand_id, name, text)

    async def write_back_fn(ctx: Context, *, history_id: str) -> bool:
        return await write_back(services, history_id)

    async def sweep_first(ctx: Context) -> None:
        # SAQ 在開始取工作的同時執行第一次 sweep；Redis 的 Lua 腳本快取是冷的時，sweep 會晚於取工作，
        # 把剛取出、還沒標記為執行中的任務當成中斷的任務中止並重排。
        # 所以在開始取工作之前先 sweep 一次：清掉前一個 worker 當掉留下的殘局，
        # 同時取得 sweep 鎖，之後 upkeep 的第一次 sweep 會直接略過。
        await ctx['worker'].queue.sweep()

    jobs = Worker(queues.jobs, [('run_job', run_job_fn)], concurrency=1, startup=[sweep_first], **options)
    tasks = Worker(
        queues.tasks,
        [('ingest', ingest_fn), ('write_back', write_back_fn)],
        concurrency=2,
        startup=[sweep_first],
        **options,
    )
    cutouts = Worker(queues.cutouts, [('cutout', cutout_fn)], concurrency=1, startup=[sweep_first], **options)
    workers = (jobs, tasks, cutouts)
    # 多個 worker 在同一個 event loop：每個 worker 自己註冊的 SIGINT/SIGTERM 處理會互相取代，
    # 只有最後啟動的那個會停下來，其他的繼續跑到被 Docker 強制終止。所以關掉，改由 main 統一處理。
    for worker in workers:
        worker.SIGNALS = []
    return workers


def stop_on_signals(workers: tuple[Worker[Context], ...]) -> None:
    """收到 SIGINT／SIGTERM 時讓所有 worker 一起停下來。Windows 不支援這個方式：Ctrl+C 會直接取消 asyncio.run。"""
    if os.name == 'nt':
        return

    def stop() -> None:
        # Worker.start() 會建立新的 event，所以要等訊號來了才去取
        for worker in workers:
            worker.event.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    # 每次呼叫 composer 都會記一行 INFO，沒有用處
    logging.getLogger('httpx').setLevel(logging.WARNING)
    services = build_services()
    queues = Queues(settings.redis_url)
    await queues.connect()
    await recover(services, queues)
    # 第一次啟動時下載模型（去背約 1 GB、RAG 約 1.2 GB）；在背景進行，不擋住生圖與文件上傳
    warming = asyncio.create_task(services.cutouts.warm_up())
    rag_warming = asyncio.create_task(warm_up_rag(services))
    requeueing = asyncio.create_task(requeue_cutouts_periodically(services, queues))
    workers = build_workers(services, queues)
    stop_on_signals(workers)
    try:
        await asyncio.gather(*(w.start() for w in workers))
    finally:
        warming.cancel()
        rag_warming.cancel()
        requeueing.cancel()
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()


if __name__ == '__main__':
    asyncio.run(main())
