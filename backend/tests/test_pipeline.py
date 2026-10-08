"""任務流程的行為：重試只針對未通過的模板、需人工審核、取消、失敗、已不在排隊時不執行。

外部服務用測試替身（不需要 composer）。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.asyncio import Redis

from app.brands import load_brands
from app.contract import (
    Brand,
    Fix,
    JobAcceptedEvent,
    JobInput,
    JobStatusEvent,
    ParsedBrief,
    ProceduralBackground,
    Product,
    PromptSpec,
    RagHit,
    Render,
    RenderBackground,
    ReviewCheck,
    TemplateId,
)
from app.db.session import Database
from app.events import EventStore
from app.pipeline.ports import Ports, ReviewResult, Rewrite, RunContext, SpecRequest
from app.pipeline.runner import run_job
from app.pipeline.sim import SimRetriever
from app.repo import catalog, jobs
from tests.fixtures import BRANDS_DIR, load_fixture

NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
JOB = 'job_p'

#: 用 selune-retry 劇本裡的一份 PromptSpec 當範本
SPEC = PromptSpec.model_validate(
    next(
        item['event']['spec']
        for item in load_fixture('timelines/selune-retry.json')['events']
        if item['event']['type'] == 'prompt.generated'
    )
)
CHECK = ReviewCheck(
    id='banned_words',
    name='禁用詞檢查',
    kind='rule',
    rule='品牌禁用詞庫',
    value='禁用詞「根治」',
    status='fail',
    target='subhead',
    rag_ref='selune#law',
)


class FakeAgent:
    def __init__(self) -> None:
        self.requests: list[SpecRequest] = []

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        raise NotImplementedError

    async def build_spec(self, request: SpecRequest) -> PromptSpec:
        self.requests.append(request)
        return SPEC.model_copy(update={'round': request.round, 'template_id': request.template.id})

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite:
        return Rewrite(fixes=[Fix(check_id='banned_words', title='文案改寫', desc='改寫')], query=None)


class FakeImage:
    def __init__(self, on_render: Any = None) -> None:
        self.on_render = on_render

    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        if self.on_render is not None:
            await self.on_render(run)
        return {
            (s.template_id, v): ProceduralBackground(kind='procedural', seed=v, palette=s.palette, style=brand.id)
            for s in specs
            for v in range(variants)
        }


class FakeReviewer:
    """passing：每一輪會通過的模板。"""

    def __init__(self, passing: dict[int, set[str]]) -> None:
        self.passing = passing

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        ok = render.template_id in self.passing.get(render.round, set())
        return ReviewResult(checks=[] if ok else [CHECK], score=90 - render.variant if ok else 40, passed=ok)


class EmptyRetriever(SimRetriever):
    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        return []


@pytest.fixture
async def store(db: Database, redis: Redis) -> AsyncIterator[EventStore]:
    data = load_fixture('timelines/selune-retry.json')
    job_input = JobInput.model_validate({**data['input'], 'variantsPerTemplate': 2, 'maxRetries': 1})
    async with db.session() as s:
        await catalog.sync_brands(s, load_brands(BRANDS_DIR)[0], NOW)
        await jobs.create_job(s, JOB, job_input, NOW)
    events = EventStore(db, redis)
    await events.append(JOB, JobAcceptedEvent(type='job.accepted', job_id=JOB))
    await events.append(JOB, JobStatusEvent(type='job.status', stage='queued', round=0))
    yield events
    await db.truncate_all()


async def messages(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return [m for m in snap.events if m['type'] != 'log']


def ports(agent: FakeAgent, reviewer: FakeReviewer, image: FakeImage | None = None) -> Ports:
    return Ports(retriever=EmptyRetriever(), agent=agent, image=image or FakeImage(), reviewer=reviewer)


async def test_retries_only_the_templates_that_failed(store: EventStore, db: Database) -> None:
    agent = FakeAgent()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post'}, 2: {'story'}})), speed=0)
    assert [(r.round, r.template.id) for r in agent.requests] == [(1, 'ig-post'), (1, 'story'), (2, 'story')]
    assert agent.requests[2].fixes == ['banned_words']
    events = await messages(db)
    completed = next(m for m in events if m['type'] == 'job.completed')
    assert completed['bestRenderIds'] == {'ig-post': f'{JOB}_r1_ig-post_v0', 'story': f'{JOB}_r2_story_v0'}
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}


async def test_asks_for_manual_review_after_the_last_retry(store: EventStore, db: Database) -> None:
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({})), speed=0)
    events = await messages(db)
    assert [m['stage'] for m in events if m['type'] == 'job.status'][-2:] == ['saving', 'needs_review']
    assert not any(m['type'] == 'job.completed' for m in events)


async def test_stops_when_the_job_is_cancelled(store: EventStore, db: Database) -> None:
    async def cancel(run: RunContext) -> None:
        async with db.session() as s:
            await jobs.request_cancel(s, JOB)
        await run.pace(300)

    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), FakeImage(cancel)), speed=1)
    events = await messages(db)
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'cancelled', 'round': 1}
    assert not any(m['type'] == 'render.completed' for m in events)


async def test_reports_a_failure_and_ends_the_job(store: EventStore, db: Database) -> None:
    async def boom(run: RunContext) -> None:
        raise RuntimeError('ComfyUI 沒有回應')

    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), FakeImage(boom)), speed=0)
    events = await messages(db)
    assert events[-2:] == [
        {**events[-2], 'type': 'job.failed', 'jobId': JOB, 'reason': 'RuntimeError: ComfyUI 沒有回應'},
        {**events[-1], 'type': 'job.status', 'stage': 'failed', 'round': 1},
    ]
    async with db.session() as s:
        summary = (await jobs.get_job(s, JOB)).summary  # type: ignore[union-attr]
    assert (summary.stage, summary.finished) == ('failed', True)


async def test_does_nothing_when_the_job_is_no_longer_queued(store: EventStore, db: Database) -> None:
    await store.append(JOB, JobStatusEvent(type='job.status', stage='cancelled', round=0))
    before = await messages(db)
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({})), speed=0)
    assert await messages(db) == before
