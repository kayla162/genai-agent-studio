"""結束階段的 job.status 與 outbox 在同一個交易內寫入；沒有設定 webhook 時不寫。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.contract import JobFailedEvent, JobStatusEvent
from app.db.models import JobEventRow, WebhookOutboxRow
from app.db.session import Database
from app.events import EventStore, WebhookTarget, webhook_target
from app.repo import jobs
from app.settings import Settings
from tests.test_catalog import alembic
from tests.test_jobs import job_input

NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
TARGET = WebhookTarget(studio_base_url='http://127.0.0.1:3000')


def status(stage: str, round_: int = 1) -> JobStatusEvent:
    return JobStatusEvent.model_validate({'type': 'job.status', 'stage': stage, 'round': round_})


@pytest.fixture
async def job(db: Database) -> AsyncIterator[str]:
    async with db.session() as s:
        await jobs.create_job(s, 'job_w', job_input(), NOW, client_ref='sheet:abc:row:2')
    yield 'job_w'
    await db.truncate_all()


async def outbox(db: Database) -> list[WebhookOutboxRow]:
    async with db.session() as s:
        return list(await s.scalars(select(WebhookOutboxRow)))


def test_webhook_target_follows_the_settings() -> None:
    assert webhook_target(Settings(_env_file=None)) is None
    configured = Settings(
        _env_file=None,
        job_webhook_url='http://n8n:5678/webhook/x',
        job_webhook_secret='s' * 32,
        studio_base_url='http://studio',
    )
    assert webhook_target(configured) == WebhookTarget(studio_base_url='http://studio')


async def test_only_the_finishing_status_writes_one_outbox_row(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('parsing', 0))
    await store.append(job, status('reviewing'))
    assert await outbox(db) == []
    await store.append(job, JobFailedEvent(type='job.failed', job_id=job, reason='composer 沒有回應'))
    await store.append(job, status('failed'))
    [row] = await outbox(db)
    assert row.id.startswith('wh_') and len(row.id) == 15
    assert (row.job_id, row.event, row.status, row.attempts, row.last_error) == (
        job,
        'job.finished',
        'pending',
        0,
        None,
    )
    assert row.next_attempt_at == row.created_at
    assert row.payload['webhookId'] == row.id
    assert (row.payload['stage'], row.payload['clientRef'], row.payload['reason']) == (
        'failed',
        'sheet:abc:row:2',
        'composer 沒有回應',
    )
    assert row.payload['studioUrl'] == f'http://127.0.0.1:3000/agent?job={job}'


async def test_a_second_finishing_status_does_not_add_a_row_or_fail(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('cancelled'))
    assert await store.append(job, status('failed')) is not None
    assert len(await outbox(db)) == 1


async def test_no_outbox_without_a_webhook(db: Database, redis: Redis, job: str) -> None:
    await EventStore(db, redis).append(job, status('done'))
    assert await outbox(db) == []


async def test_expect_stage_mismatch_writes_neither_event_nor_outbox(db: Database, redis: Redis, job: str) -> None:
    store = EventStore(db, redis, TARGET)
    await store.append(job, status('parsing', 0))
    assert await store.append(job, status('cancelled', 0), expect_stage='queued') is None
    assert await outbox(db) == []
    async with db.session() as s:
        assert [e.type for e in await s.scalars(select(JobEventRow).where(JobEventRow.job_id == job))] == ['job.status']


async def test_a_failing_payload_builder_still_finishes_the_job(
    db: Database, redis: Redis, job: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(**kwargs: object) -> dict[str, object]:
        raise KeyError('brandId')

    monkeypatch.setattr('app.events.build_job_finished', broken)
    store = EventStore(db, redis, TARGET)
    assert await store.append(job, status('done', 2)) is not None
    async with db.session() as s:
        snap = await jobs.get_job(s, job)
    assert snap is not None
    assert (snap.summary.stage, snap.summary.round) == ('done', 2)
    [row] = await outbox(db)
    assert (row.job_id, row.status) == (job, 'pending')
    assert row.payload == {
        'event': 'job.finished',
        'webhookId': row.id,
        'jobId': job,
        'clientRef': 'sheet:abc:row:2',
        'stage': 'done',
        'round': 2,
        'studioUrl': f'http://127.0.0.1:3000/agent?job={job}',
        'finishedAt': row.payload['finishedAt'],
        'payloadError': "KeyError: 'brandId'",
    }
    assert row.payload['finishedAt'].startswith('20')
    assert f'組不出任務 {job} 的 job.finished 內容' in caplog.text


def outbox_row(webhook_id: str, job_id: str, event: str) -> WebhookOutboxRow:
    return WebhookOutboxRow(
        id=webhook_id,
        job_id=job_id,
        event=event,
        payload={},
        status='pending',
        attempts=0,
        next_attempt_at=NOW,
        created_at=NOW,
    )


async def test_only_job_finished_is_unique_per_job(db: Database, job: str) -> None:
    # 選定可以有很多次（migration 0006 的部分唯一索引）；job.finished 每個任務一則
    async with db.session() as s:
        s.add_all([outbox_row('wh_a', job, 'history.selected'), outbox_row('wh_b', job, 'history.selected')])
        s.add(outbox_row('wh_c', job, 'job.finished'))
        await s.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as s:
            s.add(outbox_row('wh_d', job, 'job.finished'))
            await s.commit()


async def test_migration_0006_round_trip(db: Database, job: str) -> None:
    async with db.session() as s:
        s.add_all([outbox_row('wh_a', job, 'job.finished'), outbox_row('wh_b', job, 'history.selected')])
        await s.commit()
    await alembic(db, 'downgrade', '0005')
    try:
        # 舊的 (job_id, event) 限制：history.selected 已刪除，job.finished 保留
        assert [(r.id, r.event) for r in await outbox(db)] == [('wh_a', 'job.finished')]
    finally:
        await alembic(db, 'upgrade', 'head')
    async with db.session() as s:
        s.add_all([outbox_row('wh_c', job, 'history.selected'), outbox_row('wh_d', job, 'history.selected')])
        await s.commit()
    assert sorted(r.id for r in await outbox(db)) == ['wh_a', 'wh_c', 'wh_d']
