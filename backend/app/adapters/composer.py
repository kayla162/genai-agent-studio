"""composer（web/composer）的用戶端：版型、審查用海報的繪製與審查（REVIEW_MODE=composer）、
Gemini 的護欄（/spec、/fixes、/glyphs，AGENT_MODE=gemini），以及模擬模式沿用的前端 mock 邏輯（/sim/*）。

送出的品牌一律精簡切塊（brand_json）：品牌含上傳的手冊與歷史回寫時最多可達 2,000 個切塊，
composer 只用到每個 tag 的第一個規範（ragRefFor），所以只保留那些。"""

import base64
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.contract import (
    Brand,
    Fix,
    LayoutBox,
    ParsedBrief,
    Product,
    PromptSpec,
    RagTag,
    Render,
    ReviewCheck,
    TemplateId,
)
from app.pipeline.gemini_types import GuardIssue, SpecDraft, VlmVerdict
from app.pipeline.ports import BackgroundPalette, ReviewResult, SpecRequest


class ComposerError(Exception):
    pass


@dataclass(frozen=True)
class ProductImage:
    data: bytes
    #: 去背圖為 normal；原圖以色彩增值（multiply）合成（與前端 productImage 相同）
    blend: Literal['normal', 'multiply']


@dataclass(frozen=True)
class PosterImages:
    """worker 讀好的圖檔（送出時轉成 base64）；composer 不讀任何資料夾。"""

    #: 上傳商品的去背圖或原圖；示範商品由 composer 自己產生 SVG，為 None
    product: ProductImage | None = None
    #: 品牌的 Logo 圖檔；None 時畫向量標誌與字標
    logo: bytes | None = None
    #: 背景為 url 時的圖檔；程式產生的背景為 None
    background: bytes | None = None

    def to_json(self) -> dict[str, Any]:
        def encoded(data: bytes) -> str:
            return base64.b64encode(data).decode('ascii')

        return {
            'product': {'base64': encoded(self.product.data), 'blend': self.product.blend} if self.product else None,
            'logo': {'base64': encoded(self.logo)} if self.logo is not None else None,
            'background': {'base64': encoded(self.background)} if self.background is not None else None,
        }


@dataclass(frozen=True)
class RenderedPoster:
    png: bytes
    #: 量到的品牌主色（小寫 #rrggbb）；量不到時為 None
    measured_primary: str | None
    #: 主色色塊佔量測範圍的比例（0–1）
    primary_share: float
    #: 背景的品牌色系（X-Background-Palette）；沒有這個標頭時為 None
    background: BackgroundPalette | None = None


@dataclass(frozen=True)
class ComposerHealth:
    #: composer 啟動時註冊的海報字型（字型家族名稱）；舊版 composer 沒有回報時為空
    fonts: list[str]


def brand_json(brand: Brand) -> dict[str, Any]:
    """送給 composer 的品牌：每個 tag 只保留第一個非 -alt 的切塊（與前端 ragRefFor 選的相同，結果不變）。"""
    data = brand.to_json()
    seen: set[RagTag] = set()
    kept = []
    for chunk in brand.guideline_chunks:
        if chunk.id.endswith('-alt') or chunk.tag in seen:
            continue
        seen.add(chunk.tag)
        kept.append(chunk.to_json())
    data['guidelineChunks'] = kept
    return data


def spec_request_json(r: SpecRequest) -> dict[str, Any]:
    """POST /spec 的 request（composer 的 GuardRequest）"""
    return {
        'jobId': r.job_id,
        'round': r.round,
        'brand': brand_json(r.brand),
        'product': r.product.to_json(),
        'brief': r.brief.to_json(),
        'text': r.text,
        'templateId': r.template.id,
        'engine': r.engine,
        'seed': r.seed,
        'ragRefs': r.rag_refs,
        'fixes': r.fixes,
    }


def _error_message(res: httpx.Response) -> str:
    """composer 的錯誤回應是 { error: { code, message } }；不是時（例如經過代理）改用狀態碼與內文開頭。"""
    try:
        return str(res.json()['error']['message'])
    except (ValueError, KeyError, TypeError):
        return f'HTTP {res.status_code} {res.text[:200]}'


def _review_result(data: Any) -> ReviewResult:
    checks = [ReviewCheck.model_validate(c) for c in data['checks']]
    return ReviewResult(checks=checks, score=data['score'], passed=data['passed'])


class ComposerClient:
    def __init__(self, base_url: str, timeout: float = 30) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            res = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ComposerError(f'composer 沒有回應（{self.base_url}）：{e!r}') from e
        if res.status_code != 200:
            raise ComposerError(f'composer {path} 失敗：{_error_message(res)}')
        return res

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        return (await self._send(path, body)).json()

    async def health(self) -> ComposerHealth | None:
        """GET /health：{ status, fonts }。連不上或不是 200 時為 None。"""
        try:
            res = await self._client.get('/health')
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        try:
            fonts = res.json().get('fonts')
        except (ValueError, AttributeError):
            fonts = None
        return ComposerHealth(fonts=[str(f) for f in fonts] if isinstance(fonts, list) else [])

    async def layout(self, template_id: TemplateId) -> list[LayoutBox]:
        return [LayoutBox.model_validate(b) for b in await self._post('/layout', {'templateId': template_id})]

    async def sim_brief(self, brand: Brand, product: Product | None, text: str) -> ParsedBrief:
        body = {'brand': brand_json(brand), 'product': product.to_json() if product else None, 'text': text}
        return ParsedBrief.model_validate(await self._post('/sim/brief', body))

    async def sim_prompt(self, r: SpecRequest, flawed: bool) -> PromptSpec:
        body = {
            'jobId': r.job_id,
            'round': r.round,
            'brand': brand_json(r.brand),
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

    async def render(
        self, render: Render, product: Product | None, brand: Brand, images: PosterImages
    ) -> RenderedPoster:
        """在伺服器端繪製審查用海報（/render）：模板原始尺寸的 PNG，以及從像素量到的品牌主色與背景色系。"""
        body = {
            'render': render.to_json(),
            'product': product.to_json() if product else None,
            'brand': brand_json(brand),
            'images': images.to_json(),
        }
        res = await self._send('/render', body)
        if res.headers.get('Content-Type') != 'image/png':
            raise ComposerError(f'composer /render 沒有回傳 PNG：{res.headers.get("Content-Type")}')
        return RenderedPoster(
            png=res.content,
            measured_primary=res.headers.get('X-Measured-Primary') or None,
            primary_share=float(res.headers.get('X-Primary-Share') or 0),
            background=BackgroundPalette.model_validate_json(bg)
            if (bg := res.headers.get('X-Background-Palette'))
            else None,
        )

    async def review(
        self,
        spec: PromptSpec,
        brand: Brand,
        measured_primary: str | None,
        vlm: VlmVerdict | None = None,
        vlm_scale: float = 1.0,
        background: BackgroundPalette | None = None,
    ) -> ReviewResult:
        """live 模式的審查（/review）：8 項規則加 3 項 VLM 檢查，分數不加隨機抖動。
        vlm 有值（AGENT_MODE=gemini）時 VLM 三項用 Gemini 的判讀並比對轉錄（vlm_scale 為送出圖片與畫布的比例）；
        None 時 VLM 三項依內容判斷。background 為 /render 量到的背景色系；None 時背景色系為模擬（通過）。"""
        body: dict[str, Any] = {
            'spec': spec.to_json(),
            'brand': brand_json(brand),
            'measuredPrimary': measured_primary,
            'background': background.to_json() if background else None,
        }
        if vlm is not None:
            body |= {'vlm': vlm.to_json(), 'vlmScale': vlm_scale}
        return _review_result(await self._post('/review', body))

    async def spec(self, draft: SpecDraft, request: SpecRequest) -> tuple[PromptSpec, list[GuardIssue]]:
        """Prompt 構建的程式護欄（/spec）：可直接使用的 spec 與發現的問題。"""
        data = await self._post('/spec', {'draft': draft.to_json(), 'request': spec_request_json(request)})
        return PromptSpec.model_validate(data['spec']), [GuardIssue.model_validate(i) for i in data['issues']]

    async def fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        """Query Rewriting 的修正項（/fixes，與 /sim/fixes 相同的 planFixes）"""
        body = {'checks': [c.to_json() for c in checks], 'brand': brand_json(brand), 'spec': spec.to_json()}
        return [Fix.model_validate(f) for f in await self._post('/fixes', body)]

    async def glyphs(self, texts: list[str]) -> list[list[str]]:
        """每段文字中海報字型沒有的字（/glyphs）"""
        data = await self._post('/glyphs', {'texts': texts})
        return [[str(ch) for ch in missing] for missing in data['missing']]

    async def sim_review(self, spec: PromptSpec, brand: Brand, variant: int, seed: int) -> ReviewResult:
        body = {'spec': spec.to_json(), 'brand': brand_json(brand), 'variant': variant, 'seed': seed}
        return _review_result(await self._post('/sim/review', body))

    async def sim_fixes(self, checks: list[ReviewCheck], brand: Brand, spec: PromptSpec) -> list[Fix]:
        body = {'checks': [c.to_json() for c in checks], 'brand': brand_json(brand), 'spec': spec.to_json()}
        return [Fix.model_validate(f) for f in await self._post('/sim/fixes', body)]
