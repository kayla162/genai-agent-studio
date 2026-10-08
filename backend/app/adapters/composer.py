"""composer（web/composer）的用戶端：版型，以及模擬模式沿用的前端 mock 邏輯（/sim/*）。"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.contract import (
    Brand,
    BrandDocument,
    Fix,
    LayoutBox,
    ParsedBrief,
    Product,
    PromptSpec,
    RagChunk,
    ReviewCheck,
    TemplateId,
)
from app.pipeline.ports import ReviewResult, SpecRequest


class ComposerError(Exception):
    pass


@dataclass(frozen=True)
class SimIngest:
    dims: int
    #: 切塊與模擬向量的前幾維
    chunks: list[tuple[RagChunk, list[float]]]


class ComposerClient:
    def __init__(self, base_url: str, timeout: float = 30) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            res = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ComposerError(f'composer 沒有回應（{self.base_url}）：{e!r}') from e
        if res.status_code != 200:
            raise ComposerError(f'composer {path} 失敗：{res.json().get("error", {}).get("message", res.text)}')
        return res.json()

    async def health(self) -> bool:
        try:
            return (await self._client.get('/health')).status_code == 200
        except httpx.HTTPError:
            return False

    async def layout(self, template_id: TemplateId) -> list[LayoutBox]:
        return [LayoutBox.model_validate(b) for b in await self._post('/layout', {'templateId': template_id})]

    async def sim_brief(self, brand: Brand, product: Product | None, text: str) -> ParsedBrief:
        body = {'brand': brand.to_json(), 'product': product.to_json() if product else None, 'text': text}
        return ParsedBrief.model_validate(await self._post('/sim/brief', body))

    async def sim_prompt(self, r: SpecRequest, flawed: bool) -> PromptSpec:
        body = {
            'jobId': r.job_id,
            'round': r.round,
            'brand': r.brand.to_json(),
            'product': r.product.to_json(),
            'brief': r.brief.to_json(),
            'templateId': r.template.id,
            'engine': r.engine,
            'seed': r.seed,
            'ragRefs': r.rag_refs,
            'fixes': r.fixes,
            'flawed': flawed,
        }
        return PromptSpec.model_validate(await self._post('/sim/prompt', body))

    async def sim_review(self, spec: PromptSpec, brand: Brand, variant: int, seed: int) -> ReviewResult:
        body = {'spec': spec.to_json(), 'brand': brand.to_json(), 'variant': variant, 'seed': seed}
        data = await self._post('/sim/review', body)
        checks = [ReviewCheck.model_validate(c) for c in data['checks']]
        return ReviewResult(checks=checks, score=data['score'], passed=data['passed'])

    async def sim_fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        body = {'checks': [c.to_json() for c in checks], 'brand': brand.to_json(), 'spec': spec.to_json()}
        return [Fix.model_validate(f) for f in await self._post('/sim/fixes', body)]

    async def sim_ingest(self, brand_id: str, doc: BrandDocument) -> SimIngest:
        data = await self._post('/sim/ingest', {'brandId': brand_id, 'doc': doc.to_json()})
        chunks = [(RagChunk.model_validate(c['chunk']), list(c['preview'])) for c in data['chunks']]
        return SimIngest(dims=data['dims'], chunks=chunks)
