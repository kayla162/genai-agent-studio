import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.contract import JobAcceptedEvent, JobStatusEvent, LogEvent
from app.db.session import Database
from app.errors import NotFound
from app.events import POLL_INTERVAL, EventStore, is_final
from app.repo import jobs
from tests.test_jobs import job_input

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@pytest.fixture
async def store(db: Database, redis: Redis) -> AsyncIterator[EventStore]:
    async with db.session() as s:
        await jobs.create_job(s, 'job_e', job_input(), NOW)
    yield EventStore(db, redis)
    await db.truncate_all()


def status(stage: str, round: int = 0) -> JobStatusEvent:
    return JobStatusEvent.model_validate({'type': 'job.status', 'stage': stage, 'round': round})


def log(message: str) -> LogEvent:
    return LogEvent(type='log', source='api', level='info', message=message)


async def collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m async for m in stream]


async def test_appends_consecutive_seq_and_updates_the_summary(store: EventStore, db: Database) -> None:
    assert await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e')) == 1
    assert await store.append('job_e', status('queued')) == 2
    assert await store.append('job_e', status('parsing'), expect_stage='queued') == 3
    assert await store.append('job_e', status('cancelled'), expect_stage='queued') is None
    assert await store.append('job_e', status('done', 2)) == 4
    async with db.session() as s:
        snap = await jobs.get_job(s, 'job_e')
    assert snap is not None
    assert snap.summary.model_dump(include={'stage', 'round', 'finished'}) == {
        'stage': 'done',
        'round': 2,
        'finished': True,
    }
    assert [m['seq'] for m in snap.events] == [1, 2, 3, 4]
    assert snap.events[2] == {
        'type': 'job.status',
        'stage': 'parsing',
        'round': 0,
        'seq': 3,
        'ts': snap.events[2]['ts'],
    }


async def test_concurrent_appends_never_reuse_a_seq(store: EventStore) -> None:
    seqs = await asyncio.gather(*(store.append('job_e', log(f'#{i}')) for i in range(20)))
    assert sorted(s for s in seqs if s is not None) == list(range(1, 21))


async def test_streams_stored_events_then_live_ones_until_the_job_ends(store: EventStore) -> None:
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    await store.append('job_e', status('queued'))
    task = asyncio.create_task(collect(store.stream('job_e', after=1)))
    await asyncio.sleep(0.2)
    await store.append('job_e', status('parsing'))
    await store.append('job_e', log('working'))
    await store.append('job_e', status('done', 1))
    messages = await asyncio.wait_for(task, 5)
    assert [(m['seq'], m['type']) for m in messages] == [
        (2, 'job.status'),
        (3, 'job.status'),
        (4, 'log'),
        (5, 'job.status'),
    ]


async def test_stream_of_a_finished_job_replays_and_ends(store: EventStore) -> None:
    for e in (JobAcceptedEvent(type='job.accepted', job_id='job_e'), status('queued'), status('failed')):
        await store.append('job_e', e)
    assert [m['seq'] for m in await asyncio.wait_for(collect(store.stream('job_e')), 5)] == [1, 2, 3]
    assert await asyncio.wait_for(collect(store.stream('job_e', after=3)), 5) == []


async def test_stream_fills_gaps_from_the_database(store: EventStore, monkeypatch: pytest.MonkeyPatch) -> None:
    task = asyncio.create_task(collect(store.stream('job_e')))
    await asyncio.sleep(0.2)
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    publish = store.publish

    async def lost(job_id: str, message: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(store, 'publish', lost)
    await store.append('job_e', status('queued'))
    monkeypatch.setattr(store, 'publish', publish)
    await store.append('job_e', status('cancelled'))
    assert [m['seq'] for m in await asyncio.wait_for(task, 5)] == [1, 2, 3]


async def test_stream_ends_from_the_database_when_the_final_publish_is_lost(
    store: EventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish = store.publish

    async def drop_final(job_id: str, message: dict[str, Any]) -> None:
        if not is_final(message):
            await publish(job_id, message)

    monkeypatch.setattr(store, 'publish', drop_final)
    task = asyncio.create_task(collect(store.stream('job_e')))
    await asyncio.sleep(0.2)
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    await store.append('job_e', status('queued'))
    await store.append('job_e', status('done', 1))
    async with asyncio.timeout(5):
        messages = await task
    assert [(m['seq'], m['type']) for m in messages] == [(1, 'job.accepted'), (2, 'job.status'), (3, 'job.status')]
    assert is_final(messages[-1])


async def test_append_keeps_the_event_when_the_redis_publish_fails(
    store: EventStore, db: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    assert await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e')) == 1

    async def down(job_id: str, message: dict[str, Any]) -> None:
        raise ConnectionError('redis is down')

    monkeypatch.setattr(store, 'publish', down)
    with caplog.at_level('WARNING', logger='app.events'):
        assert await store.append('job_e', status('done', 1)) == 2
    assert 'job_e' in caplog.text
    assert 'seq 2' in caplog.text
    async with db.session() as s:
        snap = await jobs.get_job(s, 'job_e')
    assert snap is not None
    assert [(m['seq'], m['type']) for m in snap.events] == [(1, 'job.accepted'), (2, 'job.status')]
    assert (snap.summary.stage, snap.summary.finished) == ('done', True)
    monkeypatch.undo()
    assert [m['seq'] for m in await asyncio.wait_for(collect(store.stream('job_e')), 5)] == [1, 2]


class DownPubSub:
    """Redis 停止時的訂閱：subscribe 失敗，或訂閱成功後讀取時失敗（read_fails_after 次之後）。"""

    def __init__(self, *, subscribe_fails: bool, read_fails_after: int = 0) -> None:
        self.subscribe_fails = subscribe_fails
        self.reads_left = read_fails_after
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        if self.subscribe_fails:
            raise RedisConnectionError('Error 10061 connecting to 127.0.0.1:6379.')

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> None:
        if self.reads_left == 0:
            raise RedisConnectionError('Connection closed by server.')
        self.reads_left -= 1
        await asyncio.sleep(timeout)

    async def aclose(self) -> None:
        self.closed = True


async def publish_down(job_id: str, message: dict[str, Any]) -> None:
    raise RedisConnectionError('Connection refused')


@pytest.mark.parametrize(
    'down',
    [{'subscribe_fails': True}, {'subscribe_fails': False, 'read_fails_after': 1}],
    ids=['subscribe-fails', 'read-fails-later'],
)
async def test_stream_polls_the_database_every_second_when_redis_is_down(
    store: EventStore, down: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pubsub = DownPubSub(**down)
    monkeypatch.setattr(store.redis, 'pubsub', lambda: pubsub)
    monkeypatch.setattr(store, 'publish', publish_down)
    await store.append('job_e', JobAcceptedEvent(type='job.accepted', job_id='job_e'))
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for message in store.stream('job_e'):
            received.append(message)

    with caplog.at_level('WARNING', logger='app.events'):
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        # 已經在資料庫的事件立刻補送；之後的事件不經過 Redis，最多一個間隔後從資料庫讀到
        assert [m['seq'] for m in received] == [1]
        await store.append('job_e', status('queued'))
        await store.append('job_e', log('working'))
        async with asyncio.timeout(3 * POLL_INTERVAL):
            while len(received) < 3:
                await asyncio.sleep(0.05)
        assert not task.done()
        await store.append('job_e', status('done', 1))
        await asyncio.wait_for(task, 3 * POLL_INTERVAL)
    assert [(m['seq'], m['type']) for m in received] == [
        (1, 'job.accepted'),
        (2, 'job.status'),
        (3, 'log'),
        (4, 'job.status'),
    ]
    assert pubsub.closed
    assert '改為每秒從資料庫讀取' in caplog.text


async def test_unknown_jobs_raise(store: EventStore) -> None:
    with pytest.raises(NotFound):
        await collect(store.stream('nope'))
    with pytest.raises(NotFound):
        await store.append('nope', log('x'))
