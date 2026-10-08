"""SAQ worker：uv run python -m app.worker

- jobs 佇列：run_job（生圖任務，一次一個）
- tasks 佇列：cutout（去背）、ingest（品牌文件上傳）、write_back（選定海報回寫成歷史案例），最多同時兩個
- 啟動時復原：原本執行中的任務標記失敗（不自動重跑），排隊中的任務重新放回佇列
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from saq import Worker
from saq.types import Context
from sqlalchemy import select

from app.adapters.composer import ComposerClient
from app.contract import (
    BrandDocument,
    IngestChunkedEvent,
    IngestEmbeddedEvent,
    IngestStoredEvent,
    JobFailedEvent,
    JobStatusEvent,
    LogEvent,
    ProductCutout,
    ProductDraft,
)
from app.core.clock import utc_now
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError, NotFound
from app.events import EventStore
from app.pipeline.ports import Ports
from app.pipeline.runner import failure_reason, run_job
from app.pipeline.sim import sim_ports
from app.queues import Queues, ingest_channel
from app.repo import catalog, history
from app.settings import settings

RESTART_REASON = 'worker 重新啟動，任務中斷'


@dataclass
class Services:
    db: Database
    redis: Redis
    store: EventStore
    composer: ComposerClient
    ports: Ports
    #: 模擬模式的播放速度（0 為不等待）
    speed: float

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
    return Services(db, redis, EventStore(db, redis), composer, ports, settings.sim_speed)


async def cutout(services: Services, product_id: str) -> dict[str, Any]:
    """去背（模擬：約 1.2 秒，不產生圖檔，合成時以色彩增值讓白底融入背景）。"""
    async with services.db.session() as s:
        product = await catalog.get_product(s, product_id)
    if product is None:
        return {'error': f'找不到商品：{product_id}'}
    if product.photo.source == 'sample':
        return {'error': '示範商品已是去背素材'}
    await services.pace(1200)
    fields = {k: v for k, v in product.to_json().items() if k != 'createdAt'}
    cut = ProductCutout(model='BiRefNet-general', url=None)
    draft = ProductDraft.model_validate({**fields, 'cutout': cut.to_json()})
    async with services.db.session() as s:
        saved = await catalog.save_product(s, draft, utc_now())
    return {'product': saved.to_json()}


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
        await send({'error': {'code': 'invalid', 'message': failure_reason(error)}})


async def write_back(services: Services, history_id: str) -> bool:
    """選定的海報回寫成歷史案例（模擬：只標記已回寫；Plan 5 改為寫入 Chroma）。"""
    async with services.db.session() as s:
        return await history.mark_written(s, history_id)


async def recover(services: Services, queues: Queues) -> None:
    async with services.db.session() as s:
        rows = (await s.scalars(select(JobRow).where(JobRow.finished.is_(False)).order_by(JobRow.created_at))).all()
    for row in rows:
        if row.stage == 'queued':
            await queues.enqueue_job(row.id)
            continue
        await services.store.append(row.id, LogEvent(type='log', source='api', level='error', message=RESTART_REASON))
        await services.store.append(row.id, JobFailedEvent(type='job.failed', job_id=row.id, reason=RESTART_REASON))
        await services.store.append(row.id, JobStatusEvent(type='job.status', stage='failed', round=row.round))


def build_workers(services: Services, queues: Queues, **options: Any) -> tuple[Worker[Context], Worker[Context]]:
    async def run_job_fn(ctx: Context, *, job_id: str) -> None:
        await run_job(job_id, services.db, services.store, services.ports, speed=services.speed)

    async def cutout_fn(ctx: Context, *, product_id: str) -> dict[str, Any]:
        return await cutout(services, product_id)

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
        [('cutout', cutout_fn), ('ingest', ingest_fn), ('write_back', write_back_fn)],
        concurrency=2,
        startup=[sweep_first],
        **options,
    )
    return jobs, tasks


async def main() -> None:
    services = build_services()
    queues = Queues(settings.redis_url)
    await queues.connect()
    await recover(services, queues)
    jobs, tasks = build_workers(services, queues)
    try:
        await asyncio.gather(jobs.start(), tasks.start())
    finally:
        await queues.disconnect()
        await services.composer.aclose()
        await services.db.dispose()


if __name__ == '__main__':
    asyncio.run(main())
