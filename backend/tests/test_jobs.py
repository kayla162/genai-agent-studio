from datetime import UTC, datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import HistoryEntry, JobInput, Render, parse_event
from app.core.clock import iso
from app.db.session import Database
from app.events import EventStore
from app.repo import history, jobs
from tests.fixtures import load_fixture

T0 = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


def job_input() -> JobInput:
    return JobInput.model_validate(load_fixture('timelines/selune-retry.json')['input'])


async def replay_fixture(session: AsyncSession, db: Database, redis: Redis) -> tuple[str, dict[str, str]]:
    """把 selune-retry 劇本的事件寫進資料庫；回傳任務 id 與每個模板的最佳候選。"""
    data = load_fixture('timelines/selune-retry.json')
    job_id = data['jobId']
    await jobs.create_job(session, job_id, JobInput.model_validate(data['input']), T0)
    store = EventStore(db, redis)
    best: dict[str, str] = {}
    for item in data['events']:
        await store.append(job_id, parse_event(item['event']))
        if item['event']['type'] == 'job.completed':
            best = item['event']['bestRenderIds']
    return job_id, best


def test_job_ids_use_the_local_date_and_time() -> None:
    now = datetime(2026, 10, 5, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    assert jobs.make_job_id(now, suffix=0x7FFF) == 'job_20261005_0930_7fff'


async def test_lists_jobs_newest_first(session: AsyncSession) -> None:
    await jobs.create_job(session, 'job_a', job_input(), T0)
    await jobs.create_job(session, 'job_b', job_input(), T1)
    summaries = await jobs.list_jobs(session)
    assert [j.id for j in summaries] == ['job_b', 'job_a']
    assert summaries[0].model_dump(include={'stage', 'round', 'finished', 'created_at'}) == {
        'stage': 'queued',
        'round': 0,
        'finished': False,
        'created_at': '2026-10-07T02:00:00.000Z',
    }
    assert await jobs.get_job(session, 'nope') is None


async def test_cancel_is_requested_only_for_unfinished_jobs(session: AsyncSession) -> None:
    await jobs.create_job(session, 'job_a', job_input(), T0)
    assert not await jobs.cancel_requested(session, 'job_a')
    assert await jobs.request_cancel(session, 'job_a')
    assert await jobs.cancel_requested(session, 'job_a')


async def test_rebuilds_a_render_and_its_review_from_the_events(
    session: AsyncSession, db: Database, redis: Redis
) -> None:
    job_id, best = await replay_fixture(session, db, redis)
    render = await jobs.get_render(session, job_id, best['ig-post'])
    assert render is not None
    assert (render.round, render.template_id, render.passed, len(render.checks)) == (2, 'ig-post', True, 10)
    snap = await jobs.get_job(session, job_id)
    assert snap is not None
    assert snap.summary.best_render_ids == best
    assert not await jobs.request_cancel(session, job_id)
    assert await jobs.get_render(session, job_id, 'nope') is None


async def test_history_is_newest_first_per_brand_with_favorites(
    session: AsyncSession, db: Database, redis: Redis
) -> None:
    job_id, best = await replay_fixture(session, db, redis)
    render = await jobs.get_render(session, job_id, best['ig-post'])
    assert isinstance(render, Render)

    def entry(entry_id: str, at: datetime) -> HistoryEntry:
        return HistoryEntry(
            id=entry_id,
            job_id=job_id,
            brand_id='selune',
            product_id='prod_selune_serum',
            input=job_input(),
            template_id='ig-post',
            render=render,
            copy_=render.spec.copy_,
            selected_at=iso(at),
            favorite=False,
            written_to_rag=True,
        )

    await history.add_history(session, entry('hist_a', T0))
    await history.add_history(session, entry('hist_b', T1))
    assert [h.id for h in await history.list_history(session)] == ['hist_b', 'hist_a']
    assert await history.list_history(session, 'misty-isle') == []
    updated = await history.set_favorite(session, 'hist_a', True)
    assert updated is not None and updated.favorite
    assert [h.favorite for h in await history.list_history(session, 'selune')] == [False, True]
    assert await history.set_favorite(session, 'nope', True) is None
