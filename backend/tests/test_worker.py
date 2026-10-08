"""worker：任務經過佇列執行、啟動時復原、去背、品牌文件上傳、回寫。需要 composer。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import FilePhoto, JobAcceptedEvent, JobInput, JobStatusEvent, Price, ProductDraft
from app.db.session import Database
from app.events import EventStore
from app.pipeline.sim import sim_ports
from app.queues import Queues
from app.repo import catalog, jobs
from app.worker import RESTART_REASON, Services, build_workers, cutout, ingest, ingest_channel, recover
from tests.conftest import TEST_REDIS_URL
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def services(db: Database, redis: Redis, composer_url: str) -> AsyncIterator[Services]:
    composer = ComposerClient(composer_url)
    ports = sim_ports(composer, first_round_fail=True, force_all_fail=False)
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
    yield Services(db, redis, EventStore(db, redis), composer, ports, speed=0)
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


async def test_cutout_marks_uploaded_products_and_refuses_samples(services: Services, queues: Queues) -> None:
    async with services.db.session() as s:
        product = await catalog.save_product(
            s,
            ProductDraft(
                brand_id='selune',
                name='晚安面膜',
                features=[],
                price=Price(sale=0, original=0),
                photo=FilePhoto(source='upload', url='/files/products/x.png'),
                cutout=None,
            ),
            NOW,
        )
    async with running(services, queues):
        done = await queues.run_task('cutout', wait=10, product_id=product.id)
    assert done.completed
    assert done.result['product']['cutout'] == {'model': 'BiRefNet-general', 'url': None}
    assert await cutout(services, 'prod_selune_serum') == {'error': '示範商品已是去背素材'}


async def test_run_task_returns_unfinished_when_the_wait_runs_out(queues: Queues) -> None:
    """沒有 worker 時，等不到結果要回傳 completed=False，不能丟出逾時例外。"""
    loop = asyncio.get_running_loop()
    started = loop.time()
    done = await queues.run_task('cutout', wait=0.5, product_id='prod_x')
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
