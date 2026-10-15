"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：ingest（品牌文件上傳）、write_back（選定海報回寫成歷史案例），最多同時兩個
- cutouts 佇列：cutout（商品照去背，一次一個）
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務與去背中的商品重新放回佇列
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from saq import Worker
from saq.types import Context
from sqlalchemy import select

from app.adapters.composer import ComposerClient
from app.contract import (
    BrandDocument,
    FilePhoto,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
    JobFailedEvent,
    JobStatusEvent,
    LogEvent,
    ProductCutout,
)
from app.core.clock import utc_now
from app.cutout.engine import CutoutEngine
from app.cutout.processing import CutoutError
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError, NotFound
from app.events import EventStore
from app.files import photo_path, product_folder
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, history
from app.settings import Settings, settings

logger = logging.getLogger(__name__)

RESTART_REASON = 'worker 重新啟動，任務中斷'
#: 單張照片推論的逾時（秒）；等模型準備（含第一次下載）不算在內
CUTOUT_INFERENCE_TIMEOUT = 300
#: 去背推論專用的單一執行緒。逾時的推論會繼續在它的執行緒裡跑完（執行緒無法中途取消），
#: 單一執行緒確保下一張一定等它結束才開始，不會有兩個推論同時執行（每個約 6.5 GB 記憶體）。
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

    async def pace(self, ms: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms / 1000 / self.speed)


def build_services() -> Services:
    db = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    composer = ComposerClient(settings.composer_url)
    ports = sim_ports(
        composer, first_round_fail=settings.sim_first_round_fail, force_all_fail=settings.sim_force_all_fail
    )
    cutouts = CutoutEngine(settings.cutout_model, settings.models_dir, redis)
    return Services(db, redis, EventStore(db, redis), composer, ports, settings.sim_speed, settings, cutouts)


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


async def ingest(services: Services, task_id: str, brand_id: str, name: str, text: str) -> None:
    """品牌文件：切塊 → 向量化（模擬）→ 寫入；每一步發布到 Redis 頻道 ingest:{task_id}，api 以 NDJSON 串流轉給前端。"""

    async def send(message: dict[str, Any]) -> None:
        await services.redis.publish(ingest_channel(task_id), json.dumps(message, ensure_ascii=False))

    try:
        async with services.db.session() as s:
            if await catalog.get_brand(s, brand_id) is None:
                raise NotFound(f'找不到品牌：{brand_id}')
        result = await services.composer.sim_ingest(brand_id, BrandDocument(name=name, text=text))
        chunks = [c for c, _ in result.chunks]
        if not chunks:
            raise AppError('文件沒有可用的文字內容')
        await services.pace(400)
        await send(IngestChunkedEvent(type='ingest.chunked', source=name, chunks=chunks).to_json())
        for i, (chunk, preview) in enumerate(result.chunks):
            await services.pace(250)
            embedded = IngestEmbeddedEvent(
                type='ingest.embedded', chunk_id=chunk.id, index=i, total=len(chunks), dims=result.dims, preview=preview
            )
            await send(embedded.to_json())
        async with services.db.session() as s:
            await catalog.replace_document_chunks(s, brand_id, name, chunks, utc_now())
        await services.pace(300)
        await send(IngestStoredEvent(type='ingest.stored', collection=f'{brand_id}_ci', count=len(chunks)).to_json())
    except Exception as error:  # noqa: BLE001 - 錯誤一律轉給前端
        logger.exception('品牌文件上傳失敗：task_id=%s', task_id)
        await send({'error': {'code': 'invalid', 'message': failure_reason(error)}})


async def write_back(services: Services, history_id: str) -> bool:
    """選定的海報回寫成歷史案例（模擬：只標記已回寫；Plan 5 改為寫入 Chroma）。"""
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
    async with services.db.session() as s:
        pending = await catalog.pending_cutouts(s)
    for product in pending:
        if isinstance(product.photo, FilePhoto):
            await queues.enqueue_cutout(product.id, product.photo.url)


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
    # 第一次啟動時下載模型（約 1 GB）；在背景進行，不擋住生圖與文件上傳
    warming = asyncio.create_task(services.cutouts.warm_up())
    workers = build_workers(services, queues)
    stop_on_signals(workers)
    try:
        await asyncio.gather(*(w.start() for w in workers))
    finally:
        warming.cancel()
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()


if __name__ == '__main__':
    asyncio.run(main())
