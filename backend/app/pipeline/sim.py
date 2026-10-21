"""模擬版的外部服務：行為與前端 mock 劇本相同（web/src/lib/api/mock/scenario.ts）。

檢索與生圖在這裡實作；Agent 與審查透過 composer 沿用前端的 TypeScript
（buildPromptSpec、applyFlaws、reviewRender、planFixes）。
"""

from app.adapters.composer import ComposerClient
from app.contract import (
    Brand,
    ComfyQueuedEvent,
    JobInput,
    ParsedBrief,
    ProceduralBackground,
    Product,
    PromptSpec,
    RagHit,
    RagTag,
    Render,
    RenderBackground,
    RenderNode,
    RenderProgressEvent,
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import Ports, ReviewResult, Rewrite, RunContext, SpecRequest

#: 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果
VECTOR_ORDER: list[RagTag] = ['layout', 'color', 'history', 'logo', 'law']
VECTOR_SCORES = [0.86, 0.84, 0.83, 0.81, 0.79]
RERANK_ORDER: list[RagTag] = ['color', 'law', 'logo', 'layout', 'history']
RERANK_SCORES = [0.97, 0.93, 0.88, 0.74, 0.61]

#: ComfyUI 各節點的步數與時間（1× 毫秒）；每輪共 38 個 render.progress、3,200 ms
RENDER_STEPS: dict[RenderNode, tuple[int, int]] = {
    'cutout': (4, 400),
    'generate': (28, 2000),
    'relight': (4, 500),
    'upscale': (2, 300),
}
NODE_LABEL: dict[RenderNode, str] = {
    'cutout': '去背（BiRefNet）',
    'generate': '背景生成（SDXL + ControlNet + IP-Adapter）',
    'relight': '打光融合（IC-Light）',
    'upscale': '放大至 2K',
}


def seed_of(spec: PromptSpec) -> int:
    return int(next((p.value for p in spec.injection.params if p.label == 'seed'), 0))


class SimRetriever:
    async def retrieve(
        self, brand: Brand, product: Product, job_input: JobInput, run: RunContext
    ) -> tuple[str, list[RagHit]]:
        hits: list[RagHit] = []
        for tag, score in zip(VECTOR_ORDER, VECTOR_SCORES, strict=True):
            chunk = next((c for c in brand.guideline_chunks if c.tag == tag and not c.id.endswith('-alt')), None)
            if chunk is not None:
                hits.append(
                    RagHit(
                        chunk_id=chunk.id,
                        source=chunk.source,
                        section=chunk.section,
                        tag=chunk.tag,
                        text=chunk.text,
                        vector_score=score,
                    )
                )
        return f'{brand.name}｜{product.name}｜{job_input.brief}', hits

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]:
        scored = [h.model_copy(update={'rerank_score': RERANK_SCORES[RERANK_ORDER.index(h.tag)]}) for h in hits]
        return sorted(scored, key=lambda h: -(h.rerank_score or 0))

    async def requery(self, brand: Brand, query: str) -> list[RagHit]:
        chunk = next((c for c in brand.guideline_chunks if c.id == f'{brand.id}#law-alt'), None)
        if chunk is None:
            return []
        return [
            RagHit(
                chunk_id=chunk.id,
                source=chunk.source,
                section=chunk.section,
                tag=chunk.tag,
                text=chunk.text,
                vector_score=0.884,
                rerank_score=0.95,
            )
        ]


class SimAgent:
    """第一輪（或每一輪）刻意製造 mock 的四種失誤，讓審查與 Query Rewriting 有東西可以修。"""

    def __init__(self, composer: ComposerClient, *, first_round_fail: bool, force_all_fail: bool) -> None:
        self.composer = composer
        self.first_round_fail = first_round_fail
        self.force_all_fail = force_all_fail

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        return await self.composer.sim_brief(brand, product, text)

    async def build_spec(self, request: SpecRequest) -> PromptSpec:
        flawed = self.force_all_fail or (self.first_round_fail and request.round == 1)
        return await self.composer.sim_prompt(request, flawed)

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite:
        fixes = await self.composer.sim_fixes(checks, brand, spec)
        failing = {c.id for c in checks if c.status != 'pass'}
        query = f'{brand.category} 禁用詞 合規替代用語' if failing & {'banned_words', 'vlm_exaggeration'} else None
        return Rewrite(fixes=fixes, query=query)


class SimImageEngine:
    """不生圖：回報與 mock 相同的 ComfyUI 進度，背景用程序化圖（前端依 seed 與色票繪製）。"""

    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        for spec in specs:
            await run.emit(
                ComfyQueuedEvent(
                    type='comfy.queued',
                    round=round,
                    template_id=spec.template_id,
                    prompt_id=f'{job_id}_r{round}_{spec.template_id}',
                    injection=spec.injection,
                )
            )
        workflow = specs[0].injection.workflow_file
        await run.log('comfy', f'ws → ComfyUI /prompt × {len(specs)}（{workflow}，batch={variants}）')
        for node, (steps, ms) in RENDER_STEPS.items():
            for step in range(1, steps + 1):
                await run.pace(ms / steps)
                await run.emit(
                    RenderProgressEvent(type='render.progress', round=round, node=node, step=step, max_step=steps)
                )
            await run.log('comfy', f'✓ {NODE_LABEL[node]} 完成')
        return {
            (spec.template_id, v): ProceduralBackground(
                kind='procedural', seed=seed_of(spec) + v, palette=spec.palette, style=brand.id
            )
            for spec in specs
            for v in range(variants)
        }


class SimReviewer:
    def __init__(self, composer: ComposerClient) -> None:
        self.composer = composer

    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult:
        return await self.composer.sim_review(render.spec, brand, render.variant, seed)


def sim_ports(composer: ComposerClient, *, first_round_fail: bool, force_all_fail: bool) -> Ports:
    return Ports(
        retriever=SimRetriever(),
        agent=SimAgent(composer, first_round_fail=first_round_fail, force_all_fail=force_all_fail),
        image=SimImageEngine(),
        reviewer=SimReviewer(composer),
    )
