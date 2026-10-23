"""任務流程的行為：重試只針對未通過的模板、需人工審核、取消、失敗、已不在排隊時不執行、Prompt 只用前 5 筆切塊、
RAG（模型或 Chroma）無法使用時任務失敗、審查用海報傳給審查並放進 review.completed；
Prompt 構建與審查並行但事件依序送出、下一輪收到上一輪的結果、可取消的等待、不依時間軸等待、費用上限與費用合計。

外部服務用測試替身（不需要 composer）。
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
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
from app.errors import BudgetExceeded
from app.events import EventStore
from app.pipeline.ports import (
    ComposedPoster,
    Ports,
    PosterComposer,
    PreviousRound,
    Retriever,
    ReviewResult,
    Rewrite,
    RunContext,
    SpecRequest,
)
from app.pipeline.runner import PROMPT_REFS, run_job
from app.pipeline.sim import SimPosters, SimRetriever
from app.rag.encoder import Encoder
from app.rag.engine import RagEngine
from app.rag.retriever import BgeRetriever
from app.rag.store import VectorStore
from app.rag.sync import BrandLocks
from app.repo import catalog, jobs
from tests.fake_encoder import FakeEncoder, fake_engine
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


#: FakeAgent.plan_rewrite 回傳的修正項
FIX = Fix(check_id='banned_words', title='文案改寫', desc='改寫')

BuildHook = Callable[[SpecRequest, RunContext], Awaitable[None]]


class FakeAgent:
    """delays：每個模板構建 Prompt 要花的秒數（測試並行）；on_build：構建前執行（例如在等待中取消）。"""

    def __init__(self, delays: dict[str, float] | None = None, on_build: BuildHook | None = None) -> None:
        self.requests: list[SpecRequest] = []
        self.trace: list[tuple[str, str]] = []
        self.retries_left: list[int] = []
        self.delays = delays or {}
        self.on_build = on_build

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        raise NotImplementedError

    async def build_spec(self, request: SpecRequest, run: RunContext) -> PromptSpec:
        self.requests.append(request)
        self.trace.append(('start', request.template.id))
        if self.on_build is not None:
            await self.on_build(request, run)
        await asyncio.sleep(self.delays.get(request.template.id, 0))
        self.trace.append(('end', request.template.id))
        return SPEC.model_copy(update={'round': request.round, 'template_id': request.template.id})

    async def plan_rewrite(
        self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck], run: RunContext, *, retries_left: int
    ) -> Rewrite:
        self.retries_left.append(retries_left)
        return Rewrite(fixes=[FIX], query=None)


class FakeImage:
    def __init__(self, on_render: Any = None) -> None:
        self.on_render = on_render

    async def render_round(
        self,
        job_id: str,
        round: int,
        specs: list[PromptSpec],
        variants: int,
        brand: Brand,
        product: Product,
        run: RunContext,
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        if self.on_render is not None:
            await self.on_render(run)
        return {
            (s.template_id, v): ProceduralBackground(kind='procedural', seed=v, palette=s.palette, style=brand.id)
            for s in specs
            for v in range(variants)
        }


class FakeReviewer:
    """passing：每一輪會通過的模板。posters：收到的審查用海報（依候選 id）。"""

    def __init__(self, passing: dict[int, set[str]], delays: dict[int, float] | None = None) -> None:
        self.passing = passing
        self.posters: dict[str, ComposedPoster | None] = {}
        self.finished: list[str] = []
        #: 每個候選編號審查要花的秒數（測試並行）
        self.delays = delays or {}

    async def review(
        self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None, run: RunContext
    ) -> ReviewResult:
        self.posters[render.id] = poster
        await asyncio.sleep(self.delays.get(render.variant, 0))
        self.finished.append(render.id)
        ok = render.template_id in self.passing.get(render.round, set())
        return ReviewResult(checks=[] if ok else [CHECK], score=90 - render.variant if ok else 40, passed=ok)


class FakePosters:
    """每張候選都「畫」一張審查用海報（不呼叫 composer）。"""

    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster:
        return ComposedPoster(url=f'/files/jobs/{job_id}/{render.id}.png', measured_primary=brand.palette.primary)


class EmptyRetriever(SimRetriever):
    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        return []


class EightHits(EmptyRetriever):
    """召回 8 筆，Rerank 把順序整個反過來。"""

    async def retrieve(
        self, brand: Brand, product: Product, job_input: JobInput, run: RunContext
    ) -> tuple[str, list[RagHit]]:
        hits = [
            RagHit(
                chunk_id=f'selune#c{i}', source='ci.md', section='§1', tag='general', text=f'第 {i} 條', vector_score=1
            )
            for i in range(8)
        ]
        return '查詢', hits

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]:
        return [h.model_copy(update={'rerank_score': (i + 1) / 10}) for i, h in reversed(list(enumerate(hits)))]


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


class FakeUsage:
    def __init__(self, cost: Decimal, calls: int) -> None:
        self.summary = (cost, calls)

    async def job_summary(self, job_id: str) -> tuple[Decimal, int]:
        return self.summary


def ports(
    agent: FakeAgent,
    reviewer: FakeReviewer,
    image: FakeImage | None = None,
    retriever: Retriever | None = None,
    posters: PosterComposer | None = None,
    usage: FakeUsage | None = None,
) -> Ports:
    return Ports(
        retriever=retriever or EmptyRetriever(),
        agent=agent,
        image=image or FakeImage(),
        posters=posters or SimPosters(),
        reviewer=reviewer,
        usage=usage,
    )


async def test_retries_only_the_templates_that_failed(store: EventStore, db: Database) -> None:
    agent = FakeAgent()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post'}, 2: {'story'}})), speed=0)
    assert [(r.round, r.template.id) for r in agent.requests] == [(1, 'ig-post'), (1, 'story'), (2, 'story')]
    assert agent.requests[2].fixes == ['banned_words']
    events = await messages(db)
    completed = next(m for m in events if m['type'] == 'job.completed')
    assert completed['bestRenderIds'] == {'ig-post': f'{JOB}_r1_ig-post_v0', 'story': f'{JOB}_r2_story_v0'}
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'done', 'round': 2}


async def compose_logs(db: Database) -> list[str]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return [m['message'] for m in snap.events if m['type'] == 'log' and m['source'] == 'compose']


async def test_review_posters_go_to_the_review_and_into_review_completed(store: EventStore, db: Database) -> None:
    reviewer = FakeReviewer({1: {'ig-post'}, 2: {'story'}})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer, posters=FakePosters()), speed=0)
    events = await messages(db)
    completed = [m for m in events if m['type'] == 'review.completed']
    # 第 1 輪 2 個模板 × 2 張，第 2 輪重試 story 的 2 張
    assert len(completed) == 6
    for m in completed:
        url = f'/files/jobs/{JOB}/{m["renderId"]}.png'
        assert m['image'] == url
        assert reviewer.posters[m['renderId']] == ComposedPoster(url=url, measured_primary='#B76E79')
    assert await compose_logs(db) == [
        '排版引擎疊加文字圖層（4 張）',
        '✓ 伺服器端排版 4 張',
        '排版引擎疊加文字圖層（2 張）',
        '✓ 伺服器端排版 2 張',
    ]


async def test_simulated_posters_add_nothing_to_the_events(store: EventStore, db: Database) -> None:
    reviewer = FakeReviewer({1: {'ig-post', 'story'}})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer), speed=0)
    completed = [m for m in await messages(db) if m['type'] == 'review.completed']
    assert [m['image'] for m in completed] == [None] * 4
    assert set(reviewer.posters.values()) == {None}
    assert await compose_logs(db) == ['排版引擎疊加文字圖層（4 張）']


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


async def test_only_the_top_five_reranked_chunks_go_into_the_prompt(store: EventStore, db: Database) -> None:
    agent = FakeAgent()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post', 'story'}}), retriever=EightHits()), speed=0)
    events = await messages(db)
    (reranked,) = [m for m in events if m['type'] == 'rag.reranked']
    # 事件送出全部 8 筆；Prompt 只用前 5 筆
    assert [h['chunkId'] for h in reranked['hits']] == [f'selune#c{i}' for i in range(7, -1, -1)]
    assert PROMPT_REFS == 5
    assert [r.rag_refs for r in agent.requests] == [[f'selune#c{i}' for i in range(7, 2, -1)]] * 2


async def failure(db: Database) -> tuple[str, str]:
    """任務失敗的原因，以及失敗時的階段（最後一個 job.status 之前的那個）。"""
    events = await messages(db)
    stages = [m['stage'] for m in events if m['type'] == 'job.status']
    (failed,) = [m for m in events if m['type'] == 'job.failed']
    assert stages[-1] == 'failed'
    return failed['reason'], stages[-2]


async def test_fails_the_job_when_chroma_is_unreachable(store: EventStore, db: Database, redis: Redis) -> None:
    retriever = BgeRetriever(db, VectorStore('http://127.0.0.1:9'), fake_engine(redis, FakeEncoder()), BrandLocks())
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), retriever=retriever), speed=0)
    reason, stage = await failure(db)
    assert reason.startswith('向量庫（Chroma）無法連線（http://127.0.0.1:9）：')
    assert stage == 'retrieving'


async def test_fails_the_job_when_the_rag_models_cannot_be_prepared(
    store: EventStore, db: Database, redis: Redis, chroma: VectorStore, tmp_path: Path
) -> None:
    def broken(models_dir: Path) -> Encoder:
        raise RuntimeError('模型檔損毀')

    engine = RagEngine('bge', tmp_path, redis, models=[], load=broken)
    retriever = BgeRetriever(db, chroma, engine, BrandLocks())
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({}), retriever=retriever), speed=0)
    reason, stage = await failure(db)
    assert (reason, stage) == ('RAG 模型準備失敗：模型檔損毀', 'retrieving')
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    # 等候模型時先送出「RAG 模型準備中」
    logs = [m['message'] for m in snap.events if m['type'] == 'log' and m['source'] == 'rag']
    assert 'RAG 模型準備中' in logs


async def all_messages(db: Database) -> list[dict[str, Any]]:
    async with db.session() as s:
        snap = await jobs.get_job(s, JOB)
    assert snap is not None
    return snap.events


async def test_builds_prompts_in_parallel_but_sends_them_in_template_order(store: EventStore, db: Database) -> None:
    agent = FakeAgent(delays={'ig-post': 0.2})
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post', 'story'}})), speed=0)
    assert agent.trace == [('start', 'ig-post'), ('start', 'story'), ('end', 'story'), ('end', 'ig-post')]
    generated = [m['templateId'] for m in await messages(db) if m['type'] == 'prompt.generated']
    assert generated == ['ig-post', 'story']


async def test_reviews_in_parallel_but_sends_each_candidate_in_order(store: EventStore, db: Database) -> None:
    reviewer = FakeReviewer({1: set()}, delays={0: 0.2})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer), speed=0)
    # 第 1 輪：v0 比 v1 晚完成
    first_round = [r for r in reviewer.finished if '_r1_' in r]
    assert first_round == [f'{JOB}_r1_ig-post_v1', f'{JOB}_r1_story_v1', f'{JOB}_r1_ig-post_v0', f'{JOB}_r1_story_v0']
    events = [m for m in await messages(db) if m['type'] in ('review.check', 'review.completed') and m['round'] == 1]
    order = [(m['type'], m['renderId']) for m in events]
    expected: list[tuple[str, str]] = []
    for render_id in [f'{JOB}_r1_ig-post_v0', f'{JOB}_r1_ig-post_v1', f'{JOB}_r1_story_v0', f'{JOB}_r1_story_v1']:
        expected += [('review.check', render_id), ('review.completed', render_id)]
    assert order == expected


async def test_the_next_round_gets_the_previous_round_and_the_prompt_hits(store: EventStore, db: Database) -> None:
    agent = FakeAgent()
    await run_job(JOB, db, store, ports(agent, FakeReviewer({1: {'ig-post'}, 2: {'story'}})), speed=0)
    first, _, retry = agent.requests
    assert first.previous is None
    assert retry.previous == PreviousRound(
        spec=SPEC.model_copy(update={'round': 1, 'template_id': 'story'}), checks=[CHECK], fixes=[FIX]
    )
    data = load_fixture('timelines/selune-retry.json')
    assert first.text == data['input']['brief']
    assert [h.chunk_id for h in first.hits] == first.rag_refs
    assert agent.retries_left == [1]


async def test_skips_the_timeline_when_phases_are_not_paced(store: EventStore, db: Database) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    reviewer = FakeReviewer({1: {'ig-post', 'story'}})
    await run_job(JOB, db, store, ports(FakeAgent(), reviewer), speed=1, pace_phases=False)
    assert loop.time() - started < 1.5
    assert (await messages(db))[-1]['stage'] == 'done'


async def test_cancelling_interrupts_a_wait_within_a_second(store: EventStore, db: Database) -> None:
    async def hang(request: SpecRequest, run: RunContext) -> None:
        if request.template.id == 'story':
            async with db.session() as s:
                await jobs.request_cancel(s, JOB)
            await run.wait(asyncio.sleep(30), note='已中斷進行中的 Gemini 呼叫')

    loop = asyncio.get_running_loop()
    started = loop.time()
    await run_job(JOB, db, store, ports(FakeAgent(on_build=hang), FakeReviewer({})), speed=0)
    assert loop.time() - started < 2
    events = await all_messages(db)
    assert events[-1] == {**events[-1], 'type': 'job.status', 'stage': 'cancelled'}
    assert events[-2] == {**events[-2], 'type': 'log', 'level': 'warn', 'message': '已中斷進行中的 Gemini 呼叫'}
    assert not any(m['type'] == 'prompt.generated' for m in events)


async def test_the_budget_fails_the_job_with_its_reason(store: EventStore, db: Database) -> None:
    async def over(request: SpecRequest, run: RunContext) -> None:
        raise BudgetExceeded('已達單一任務的 Gemini 費用上限（US$1.00，已用 US$1.02）')

    await run_job(JOB, db, store, ports(FakeAgent(on_build=over), FakeReviewer({})), speed=0)
    reason, stage = await failure(db)
    assert (reason, stage) == ('已達單一任務的 Gemini 費用上限（US$1.00，已用 US$1.02）', 'prompting')


async def test_reports_the_job_cost_when_saving(store: EventStore, db: Database) -> None:
    usage = FakeUsage(Decimal('0.183'), 17)
    await run_job(JOB, db, store, ports(FakeAgent(), FakeReviewer({1: {'ig-post', 'story'}}), usage=usage), speed=0)
    events = await all_messages(db)
    saving = next(i for i, m in enumerate(events) if m['type'] == 'job.status' and m['stage'] == 'saving')
    logs = [m['message'] for m in events[saving:] if m['type'] == 'log']
    assert '本任務 Gemini 費用 US$0.18（17 次呼叫）' in logs
