"""任務流程（Orchestrator）：階段與事件順序與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

需求拆解 → RAG 檢索 → Rerank → 每一輪：Prompt 構建 → 生圖 → 排版 → 審查 → 未通過的模板 Query Rewriting 後重試
→ 寫入結果。重試以模板為單位。
模擬模式依 1× 時間軸等待（speed 倍速，0 為不等待）；真實版各步驟本身就會花時間。
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass

from app.contract import (
    Brand,
    BriefParsedEvent,
    ChannelTemplate,
    CheckId,
    JobCompletedEvent,
    JobEvent,
    JobFailedEvent,
    JobInput,
    JobNeedsReviewEvent,
    JobStage,
    JobStatusEvent,
    LogEvent,
    LogLevel,
    LogSource,
    Product,
    PromptGeneratedEvent,
    PromptSpec,
    RagRerankedEvent,
    RagRetrievedEvent,
    Render,
    RenderCompletedEvent,
    ReviewCheckEvent,
    ReviewCompletedEvent,
    RewriteStartedEvent,
    TemplateId,
)
from app.core.rng import Mulberry32, hash_string
from app.db.models import JobRow
from app.db.session import Database
from app.errors import AppError
from app.events import EventStore
from app.pipeline.ports import Ports, ReviewResult, SpecRequest
from app.repo import catalog, jobs
from app.templates import get_template

logger = logging.getLogger(__name__)

#: 1× 速度下各階段的時間（毫秒），與 mock 的 PHASE_MS 相同
PHASE_MS = {
    'parse': 800,
    'retrieve_start': 1100,
    'retrieved': 1600,
    'reranked': 2300,
    'prompt': 800,
    'compose': 300,
    'review': 1200,
    'rewrite': 800,
    'save': 400,
}
#: 取消旗標最多隔多久檢查一次（秒）
CANCEL_CHECK_INTERVAL = 0.25
#: Rerank 後進入 Prompt 的切塊數（ragRefs）；真實版召回 8 筆，模擬版只有 5 筆
PROMPT_REFS = 5


class JobCancelled(Exception):
    pass


def truncate(s: str, n: int) -> str:
    return s[:n] + '…' if len(s) > n else s


def failure_reason(error: Exception) -> str:
    return error.message if isinstance(error, AppError) else f'{type(error).__name__}: {error}'


class JobRun:
    """一個任務的執行狀態：送出事件、log、依時間軸等待、檢查取消。"""

    def __init__(self, job_id: str, db: Database, store: EventStore, speed: float) -> None:
        self.job_id = job_id
        self.db = db
        self.store = store
        self.speed = speed
        self.round = 0
        self._checked_at = 0.0

    async def checkpoint(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked_at < CANCEL_CHECK_INTERVAL:
            return
        self._checked_at = now
        async with self.db.session() as s:
            if await jobs.cancel_requested(s, self.job_id):
                raise JobCancelled()

    async def emit(self, event: JobEvent) -> None:
        await self.checkpoint()
        if isinstance(event, JobStatusEvent):
            self.round = event.round
        await self.store.append(self.job_id, event)

    async def status(self, stage: JobStage, round: int) -> None:
        await self.emit(JobStatusEvent(type='job.status', stage=stage, round=round))

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        await self.emit(LogEvent(type='log', source=source, level=level, message=message))

    async def pace(self, ms: float) -> None:
        if self.speed <= 0 or ms <= 0:
            return
        remaining = ms / 1000 / self.speed
        while remaining > 0:
            step = min(CANCEL_CHECK_INTERVAL, remaining)
            await asyncio.sleep(step)
            remaining -= step
            await self.checkpoint(force=True)


@dataclass(frozen=True)
class JobContext:
    job_id: str
    job_input: JobInput
    brand: Brand
    product: Product
    templates: list[ChannelTemplate]


@dataclass(frozen=True)
class Reviewed:
    render: Render
    result: ReviewResult


async def run_job(job_id: str, db: Database, store: EventStore, ports: Ports, *, speed: float) -> None:
    """執行一個排隊中的任務。任務已不在排隊（例如已取消）時直接結束。"""
    run = JobRun(job_id, db, store, speed)
    claimed = await store.append(
        job_id, JobStatusEvent(type='job.status', stage='parsing', round=0), expect_stage='queued'
    )
    if claimed is None:
        return
    try:
        ctx = await _load(db, job_id)
        await _pipeline(run, ctx, ports)
    except JobCancelled:
        await store.append(job_id, JobStatusEvent(type='job.status', stage='cancelled', round=run.round))
    except Exception as error:  # noqa: BLE001 - 任何錯誤都要讓任務結束並回報原因
        logger.exception('任務執行失敗：job_id=%s', job_id)
        reason = failure_reason(error)
        await store.append(job_id, LogEvent(type='log', source='api', level='error', message=reason))
        await store.append(job_id, JobFailedEvent(type='job.failed', job_id=job_id, reason=reason))
        await store.append(job_id, JobStatusEvent(type='job.status', stage='failed', round=run.round))


async def _load(db: Database, job_id: str) -> JobContext:
    async with db.session() as s:
        row = await s.get(JobRow, job_id)
        assert row is not None
        job_input = JobInput.model_validate(row.input)
        brand = await catalog.get_brand(s, job_input.brand_id)
        product = await catalog.get_product(s, job_input.product_id)
    if brand is None:
        raise AppError(f'找不到品牌：{job_input.brand_id}')
    if product is None:
        raise AppError(f'找不到商品：{job_input.product_id}（可能已被刪除）')
    templates = [get_template(t) for t in job_input.template_ids]
    return JobContext(job_id, job_input, brand, product, templates)


async def _pipeline(run: JobRun, ctx: JobContext, ports: Ports) -> None:
    job_id, inp, brand, product = ctx.job_id, ctx.job_input, ctx.brand, ctx.product
    job_seed = hash_string(job_id)
    rng = Mulberry32(job_seed)

    # 1. 需求拆解：沿用使用者在表單確認過的欄位
    await run.log('ws', f'→ job.create brand={brand.id} product={product.id} templates={",".join(inp.template_ids)}')
    await run.pace(300)
    await run.log('agent', f'{inp.llm}：拆解需求「{truncate(inp.brief, 24)}」')
    await run.pace(PHASE_MS['parse'] - 300)
    await run.emit(BriefParsedEvent(type='brief.parsed', parsed_brief=inp.parsed_brief))
    pb = inp.parsed_brief
    await run.log('agent', f'✓ 語氣={pb.tone}・檔期={pb.campaign or "無"}・優惠={pb.offer or "無"}', 'ok')

    # 2. RAG：召回 → Rerank
    await run.pace(PHASE_MS['retrieve_start'] - PHASE_MS['parse'])
    await run.status('retrieving', 0)
    await run.log('rag', f'embed query（bge-m3）→ similarity_search(collection="{brand.id}_ci")')
    query, hits = await ports.retriever.retrieve(brand, product, inp, run)
    await run.pace(PHASE_MS['retrieved'] - PHASE_MS['retrieve_start'])
    await run.emit(RagRetrievedEvent(type='rag.retrieved', query=query, hits=hits))
    await run.log('rag', f'召回 {len(hits)} 筆品牌規範')
    ranked = await ports.retriever.rerank(query, hits)
    await run.pace(PHASE_MS['reranked'] - PHASE_MS['retrieved'])
    await run.emit(RagRerankedEvent(type='rag.reranked', hits=ranked))
    await run.log('rag', f'✓ BGE Reranker 重新排序：{" > ".join(h.tag for h in ranked)}', 'ok')
    rag_refs = [h.chunk_id for h in ranked[:PROMPT_REFS]]

    round = 1
    pending = list(ctx.templates)
    fixes_next: list[CheckId] = []
    best: dict[TemplateId, str] = {}
    requeried = False
    success = False
    while True:
        # 3. Prompt 構建
        await run.status('prompting', round)
        specs: list[PromptSpec] = []
        for template in pending:
            seed = 100_000_000 + math.floor(rng() * 900_000_000)
            request = SpecRequest(
                job_id, round, brand, product, inp.parsed_brief, template, inp.engine, seed, list(rag_refs), fixes_next
            )
            specs.append(await ports.agent.build_spec(request))
        for spec in specs:
            await run.pace(PHASE_MS['prompt'] / len(specs))
            await run.emit(
                PromptGeneratedEvent(type='prompt.generated', round=round, template_id=spec.template_id, spec=spec)
            )
        boxes = len(specs[0].layout)
        await run.log('agent', f'✓ 第 {round} 輪 JSON Prompt：{len(specs)} 個模板 × {boxes} 個 BBox', 'ok')

        # 4. 生圖
        await run.status('rendering', round)
        backgrounds = await ports.image.render_round(job_id, round, specs, inp.variants_per_template, brand, run)
        renders = [
            Render(
                id=f'{job_id}_r{round}_{spec.template_id}_v{v}',
                job_id=job_id,
                round=round,
                template_id=spec.template_id,
                variant=v,
                background=backgrounds[(spec.template_id, v)],
                spec=spec,
                score=None,
                passed=None,
                checks=[],
            )
            for spec in specs
            for v in range(inp.variants_per_template)
        ]
        await run.emit(RenderCompletedEvent(type='render.completed', round=round, renders=renders))

        # 5. 文字排版合成
        await run.status('composing', round)
        await run.log('compose', f'排版引擎疊加文字圖層（{len(renders)} 張）')
        await run.pace(PHASE_MS['compose'])

        # 6. 合規審查（規則 + VLM）
        await run.status('reviewing', round)
        await run.log('vlm', f'{inp.vlm}：審查 {len(renders)} 張 × 10 項')
        reviewed = [Reviewed(r, await ports.reviewer.review(brand, r, hash_string(r.id) ^ job_seed)) for r in renders]
        dt = PHASE_MS['review'] / max(1, sum(len(x.result.checks) for x in reviewed))
        for x in reviewed:
            for check in x.result.checks:
                await run.pace(dt)
                await run.emit(ReviewCheckEvent(type='review.check', round=round, render_id=x.render.id, check=check))
            await run.emit(
                ReviewCompletedEvent(
                    type='review.completed',
                    round=round,
                    render_id=x.render.id,
                    score=x.result.score,
                    passed=x.result.passed,
                    image=None,
                )
            )

        def by_score(template_id: TemplateId, round_reviews: list[Reviewed] = reviewed) -> list[Reviewed]:
            return sorted(
                (x for x in round_reviews if x.render.template_id == template_id), key=lambda x: -x.result.score
            )

        failed: list[ChannelTemplate] = []
        for template in pending:
            top = next((x for x in by_score(template.id) if x.result.passed), None)
            if top is not None:
                best[template.id] = top.render.id
            else:
                failed.append(template)
        passed = len(pending) - len(failed)
        await run.log('vlm', f'第 {round} 輪：{passed}/{len(pending)} 個模板通過', 'warn' if failed else 'ok')
        if not failed:
            success = True
            break
        if round > inp.max_retries:
            break

        # 7. Query Rewriting（必要時重新檢索合規用語）
        await run.status('rewriting', round)
        reasons: list[CheckId] = []
        requery: str | None = None
        for template in failed:
            top = by_score(template.id)[0]
            failing = [c.id for c in top.result.checks if c.status != 'pass']
            reasons += [c for c in failing if c not in reasons]
            rewrite = await ports.agent.plan_rewrite(brand, top.render.spec, top.result.checks)
            requery = requery or rewrite.query
            await run.emit(
                RewriteStartedEvent(
                    type='rewrite.started',
                    round=round,
                    template_id=template.id,
                    reasons=failing,
                    fixes=rewrite.fixes,
                    requery=rewrite.query is not None and not requeried,
                )
            )
        await run.log('api', f'觸發 Query Rewriting（重試 {round}/{inp.max_retries}）', 'warn')
        if requery is not None and not requeried:
            await run.pace(PHASE_MS['rewrite'] / 2)
            requery_hits = await ports.retriever.requery(brand, requery)
            await run.emit(RagRetrievedEvent(type='rag.retrieved', query=requery, hits=requery_hits))
            for hit in requery_hits:
                await run.log('rag', f're-query → {hit.chunk_id}（{hit.vector_score:.3f}）', 'ok')
            rag_refs += [h.chunk_id for h in requery_hits if h.chunk_id not in rag_refs]
            requeried = True
            await run.pace(PHASE_MS['rewrite'] / 2)
        else:
            await run.pace(PHASE_MS['rewrite'])
        fixes_next = fixes_next + [c for c in reasons if c not in fixes_next]
        pending = failed
        round += 1

    # 8. 寫入結果；結束的 job.status 一定是最後一則事件
    await run.status('saving', round)
    await run.log('db', f'INSERT INTO renders（{len(best)} 張最佳候選）')
    await run.pace(PHASE_MS['save'])
    if success:
        await run.emit(JobCompletedEvent(type='job.completed', job_id=job_id, best_render_ids=best))
        await run.log('ws', '← job.completed', 'ok')
        await run.status('done', round)
    else:
        reason = '已達最大重試次數，仍未通過合規審查'
        await run.emit(JobNeedsReviewEvent(type='job.needs_review', job_id=job_id, reason=reason))
        await run.log('ws', '← job.needs_review', 'warn')
        await run.status('needs_review', round)
