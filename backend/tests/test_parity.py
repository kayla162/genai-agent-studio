"""模擬模式的任務流程與前端 mock 劇本（contracts/fixtures/timelines/）產生完全相同的事件。

比對除了 log 以外的每一則事件（內容與順序）；需要 composer（測試會自動啟動）。
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import JobAcceptedEvent, JobInput, JobStatusEvent
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
