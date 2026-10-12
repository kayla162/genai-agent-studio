"""模擬模式的任務流程與前端 mock 劇本（contracts/fixtures/timelines/）產生完全相同的事件。

比對除了 log 以外的每一則事件（內容與順序）；需要 composer（測試會自動啟動）。
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import FilePhoto, JobAcceptedEvent, JobInput, JobStatusEvent, Price, ProductDraft
from app.db.session import Database
from app.events import EventStore
from app.pipeline.runner import run_job
from app.pipeline.sim import sim_ports
from app.repo import catalog, jobs
from tests.fixtures import BRANDS_DIR, TIMELINES, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


def without_meta(message: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in message.items() if k not in ('seq', 'ts')}


@pytest.mark.parametrize('name', TIMELINES)
async def test_simulated_pipeline_matches_the_mock_timeline(
    name: str, db: Database, redis: Redis, composer_url: str
) -> None:
    data = load_fixture(f'timelines/{name}.json')
    job_id, demo = data['jobId'], data['demo']
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, job_id, JobInput.model_validate(data['input']), NOW)
    store = EventStore(db, redis)
    await store.append(job_id, JobAcceptedEvent(type='job.accepted', job_id=job_id))
    await store.append(job_id, JobStatusEvent(type='job.status', stage='queued', round=0))
    composer = ComposerClient(composer_url)
    try:
        ports = sim_ports(composer, first_round_fail=demo['firstRoundFail'], force_all_fail=demo['forceAllFail'])
        await run_job(job_id, db, store, ports, speed=0)
    finally:
        await composer.aclose()
    async with db.session() as s:
        snap = await jobs.get_job(s, job_id)
    assert snap is not None
    actual = [
        without_meta(m)
        for m in snap.events
        if m['type'] != 'log' and not (m['type'] == 'job.status' and m['stage'] == 'queued')
    ]
    expected = [item['event'] for item in data['events'] if item['event']['type'] != 'log']
    assert actual == expected
    assert snap.events[-1]['type'] == 'job.status'
    await db.truncate_all()


async def test_a_brand_made_from_the_template_also_fails_first_and_passes_after_rewriting(
    tmp_path: Path, db: Database, redis: Redis, composer_url: str
) -> None:
    """使用者自己的品牌（複製 _template.yaml）：第一輪的失誤由品牌的主色與禁用詞推算。"""
    shutil.copy(BRANDS_DIR / '_template.yaml', tmp_path / 'my-brand.yaml')
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    data = load_fixture('timelines/selune-retry.json')
    job_input = JobInput.model_validate({**data['input'], 'brandId': 'my-brand', 'productId': 'prod_mine'})
    product = ProductDraft(
        id='prod_mine',
        brand_id='my-brand',
        name='晚安面膜',
        features=['玻尿酸'],
        price=Price(sale=590, original=790),
        photo=FilePhoto(source='upload', url='/files/uploads/mine.png'),
        cutout=None,
    )
    async with db.session() as s:
        await catalog.sync_brands(s, loaded, NOW)
        await catalog.save_product(s, product, NOW)
        await jobs.create_job(s, 'job_mine', job_input, NOW)
    store = EventStore(db, redis)
    await store.append('job_mine', JobAcceptedEvent(type='job.accepted', job_id='job_mine'))
    await store.append('job_mine', JobStatusEvent(type='job.status', stage='queued', round=0))
    composer = ComposerClient(composer_url)
    try:
        await run_job('job_mine', db, store, sim_ports(composer, first_round_fail=True, force_all_fail=False), speed=0)
    finally:
        await composer.aclose()
    async with db.session() as s:
        snap = await jobs.get_job(s, 'job_mine')
    assert snap is not None
    assert (snap.summary.stage, snap.summary.round) == ('done', 2)
    reasons = {r for m in snap.events if m['type'] == 'rewrite.started' for r in m['reasons']}
    assert {'color_delta', 'banned_words'} <= reasons
    await db.truncate_all()
