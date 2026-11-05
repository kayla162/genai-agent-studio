"""發送：2xx 送達、4xx 直接 dead、5xx／408／429／連線錯誤依退避表重試、第 8 次 dead；只取到期的 pending。"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import WebhookOutboxRow
from app.db.session import Database
from app.repo import jobs
from app.settings import Settings
from app.webhooks.delivery import BACKOFF, MAX_ATTEMPTS, Outcome, apply_outcome, deliver_due
from app.webhooks.signing import encode, sign
from tests.test_jobs import job_input

URL = 'http://n8n.test/webhook/poster-job-finished'
SECRET = 's' * 32
NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
SETTINGS = Settings(_env_file=None, image_mode='sim', agent_mode='sim', job_webhook_url=URL, job_webhook_secret=SECRET)


def outbox_row(
    id_: str, *, status: str = 'pending', attempts: int = 0, due: datetime = NOW, last_error: str | None = None
) -> WebhookOutboxRow:
    return WebhookOutboxRow(
        id=id_,
        job_id=f'job_{id_}',
        event='job.finished',
        payload={'event': 'job.finished', 'webhookId': id_},
        status=status,
        attempts=attempts,
        next_attempt_at=due,
        created_at=NOW,
    )


@pytest.fixture
async def seeded(db: Database) -> AsyncIterator[Database]:
    yield db
    await db.truncate_all()


async def add(db: Database, *rows: WebhookOutboxRow) -> None:
    # (job_id, event) 唯一：每筆通知各自對應一個任務
    async with db.session() as s:
        for row in rows:
            await jobs.create_job(s, row.job_id, job_input(), NOW)
        s.add_all(rows)
        await s.commit()


async def get(db: Database, id_: str) -> WebhookOutboxRow:
    async with db.session() as s:
        row = await s.get(WebhookOutboxRow, id_)
        assert row is not None
        return row


def test_apply_outcome_follows_the_backoff_table() -> None:
    row = outbox_row('wh_a')
    for n, wait in enumerate(BACKOFF, start=1):
        apply_outcome(row, Outcome(False, True, 'HTTP 503'), NOW)
        assert (row.status, row.attempts, row.next_attempt_at) == ('pending', n, NOW + timedelta(seconds=wait))
    apply_outcome(row, Outcome(False, True, 'HTTP 503'), NOW)
    assert (row.status, row.attempts, row.last_error) == ('dead', MAX_ATTEMPTS, 'HTTP 503')


def test_apply_outcome_delivered_and_permanent_failure() -> None:
    ok = outbox_row('wh_b', attempts=2, last_error='HTTP 503')
    apply_outcome(ok, Outcome(True, False, None), NOW)
    assert (ok.status, ok.attempts, ok.delivered_at, ok.last_error) == ('delivered', 3, NOW, None)
    bad = outbox_row('wh_c')
    apply_outcome(bad, Outcome(False, False, 'HTTP 401：bad signature'), NOW)
    assert (bad.status, bad.attempts, bad.last_error) == ('dead', 1, 'HTTP 401：bad signature')


@respx.mock
async def test_deliver_due_sends_signed_body_and_records_results(seeded: Database) -> None:
    await add(
        seeded,
        outbox_row('wh_ok'),
        outbox_row('wh_4xx'),
        outbox_row('wh_5xx'),
        outbox_row('wh_429'),
        outbox_row('wh_later', due=NOW + timedelta(seconds=1)),
        outbox_row('wh_dead', status='dead'),
    )
    codes = {'wh_ok': 204, 'wh_4xx': 401, 'wh_5xx': 502, 'wh_429': 429}
    route = respx.post(URL).mock(side_effect=lambda r: httpx.Response(codes[r.headers['X-Webhook-Id']], text='nope'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, lambda: NOW) == 1
    assert route.call_count == 4
    sent = next(c.request for c in route.calls if c.request.headers['X-Webhook-Id'] == 'wh_ok')
    body = encode({'event': 'job.finished', 'webhookId': 'wh_ok'})
    assert sent.content == body
    ts = int(sent.headers['X-Webhook-Timestamp'])
    assert ts == int(NOW.timestamp())
    assert sent.headers['X-Webhook-Signature'] == sign(SECRET, ts, body)
    assert (await get(seeded, 'wh_ok')).status == 'delivered'
    assert (await get(seeded, 'wh_4xx')).status == 'dead'
    assert (await get(seeded, 'wh_4xx')).last_error == 'HTTP 401：nope'
    for retried in ('wh_5xx', 'wh_429'):
        row = await get(seeded, retried)
        assert (row.status, row.attempts, row.next_attempt_at) == ('pending', 1, NOW + timedelta(seconds=BACKOFF[0]))
    assert (await get(seeded, 'wh_later')).attempts == 0


@respx.mock
async def test_connection_errors_are_retried(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_x'))
    respx.post(URL).mock(side_effect=httpx.ConnectError('connection refused'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, lambda: NOW) == 0
    row = await get(seeded, 'wh_x')
    assert (row.status, row.attempts) == ('pending', 1)
    assert row.last_error is not None and row.last_error.startswith('連線失敗')


@respx.mock
async def test_concurrent_deliveries_do_not_send_the_same_row_twice(seeded: Database) -> None:
    await add(seeded, *(outbox_row(f'wh_{i}') for i in range(5)))

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    route = respx.post(URL).mock(side_effect=slow)
    async with httpx.AsyncClient() as http:
        counts = await asyncio.gather(*(deliver_due(seeded, SETTINGS, http, lambda: NOW) for _ in range(3)))
    assert sum(counts) == 5
    assert route.call_count == 5


async def test_nothing_happens_without_a_webhook_url(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_off'))
    async with httpx.AsyncClient() as http:
        assert (
            await deliver_due(seeded, Settings(_env_file=None, image_mode='sim', agent_mode='sim'), http, lambda: NOW)
            == 0
        )
    async with seeded.session() as s:
        assert [r.attempts for r in await s.scalars(select(WebhookOutboxRow))] == [0]


@respx.mock
async def test_one_failing_row_does_not_undo_the_others(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_good'), outbox_row('wh_bad', due=NOW + timedelta(seconds=0)))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers['X-Webhook-Id'] == 'wh_bad':
            raise ValueError('boom')
        return httpx.Response(200)

    respx.post(URL).mock(side_effect=handler)
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, lambda: NOW) == 1
    assert (await get(seeded, 'wh_good')).status == 'delivered'
    bad = await get(seeded, 'wh_bad')
    assert (bad.status, bad.attempts) == ('pending', 1)
    assert bad.last_error is not None and bad.last_error.startswith('發送失敗')


@respx.mock
async def test_nul_characters_are_stripped_from_the_stored_error(seeded: Database) -> None:
    await add(seeded, outbox_row('wh_nul'))
    respx.post(URL).mock(return_value=httpx.Response(500, text='bad\x00body'))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, lambda: NOW) == 0
    row = await get(seeded, 'wh_nul')
    assert (row.status, row.attempts, row.last_error) == ('pending', 1, 'HTTP 500：badbody')


@respx.mock
async def test_each_row_is_signed_with_the_clock_read_for_that_row(seeded: Database) -> None:
    await add(
        seeded, outbox_row('wh_1', due=NOW - timedelta(seconds=2)), outbox_row('wh_2', due=NOW - timedelta(seconds=1))
    )
    times = iter([NOW, NOW + timedelta(seconds=200), NOW + timedelta(seconds=400)])
    route = respx.post(URL).mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        assert await deliver_due(seeded, SETTINGS, http, lambda: next(times)) == 2
    stamps = {c.request.headers['X-Webhook-Id']: int(c.request.headers['X-Webhook-Timestamp']) for c in route.calls}
    assert stamps == {'wh_1': int(NOW.timestamp()), 'wh_2': int((NOW + timedelta(seconds=200)).timestamp())}
    assert (await get(seeded, 'wh_2')).delivered_at == NOW + timedelta(seconds=200)
