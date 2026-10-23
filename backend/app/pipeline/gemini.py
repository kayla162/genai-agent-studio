"""AGENT_MODE=gemini 的 Agent：Gemini 負責需求拆解、Prompt 構建與 Query Rewriting。

- 提示詞的系統指示放在 prompts/*.md（固定，讓隱式快取有機會命中）；動態的資料以 JSON 放在 user 訊息。
- Prompt 構建的程式護欄在 composer 的 /spec（與審查共用同一套文案與幾何函式）：第一次有需要重問的問題時，
  帶著中文說明重問一次；第二次直接使用 /spec 回傳的 spec（仍有問題的欄位已改用預設），並以 warn log 顯示。
- 需求拆解與 Query Rewriting 的護欄在這裡（規格 §4.3、§4.5）。
"""

import asyncio
import io
import json
import logging
import re
from collections.abc import Awaitable
from functools import cache
from pathlib import Path
from typing import Any, TypeVar

from PIL import Image, ImageOps

from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiCall, LlmClient
from app.contract import (
    Brand,
    CheckId,
    Fix,
    JobEvent,
    LogLevel,
    LogSource,
    ParsedBrief,
    Product,
    PromptSpec,
    ReviewCheck,
    Tone,
)
from app.files import resolve_url
from app.pipeline.gemini_types import BriefDraft, GuardIssue, RewriteDraft, SpecDraft
from app.pipeline.ports import Agent, Rewrite, RunContext, SpecRequest
from app.settings import Settings
from app.usage import UsageScope

logger = logging.getLogger(__name__)

T = TypeVar('T')

PROMPTS_DIR = Path(__file__).parent / 'prompts'

#: 四種語氣的說明（需求拆解的提示詞）
TONE_NOTES: dict[Tone, str] = {
    'gentle': '溫柔療癒：柔和、安心、有陪伴感，多用感受描述',
    'science': '專業科研：成分、數據與研究感，語氣精準',
    'playful': '活潑年輕：輕快、口語化、有趣，可以用驚嘆號',
    'minimal': '簡約：字少、留白多，只說最重要的一件事',
}
#: 示範商品的向量素材尺寸（web/src/lib/compose/art.ts 的 productArtSvg）
SAMPLE_ART_SIZE = (500, 800)
#: 文案長度上限（視覺寬度），與 web/src/lib/agent/guard.ts 的 LIMITS 相同
COPY_LIMITS = {
    'headline': 8,
    'subhead': 22,
    'feature': 12,
    'badgeTop': 6,
    'badgeMain': 6,
    'priceLabel': 8,
    'badgeSub': 16,
}
#: Query Rewriting 修正項的長度上限（字）
FIX_TITLE_CHARS = 8
FIX_DESC_CHARS = 80
#: rationale 在 log 中最多顯示的字數
RATIONALE_CHARS = 60
#: 禁用詞或誇大用語未通過、Gemini 沒有給查詢時的重新檢索（與模擬版相同）
REQUERY_CHECKS: frozenset[CheckId] = frozenset({'banned_words', 'vlm_exaggeration'})

#: 護欄的問題在第二次之後的處理方式（warn log 的結尾）
COPY_CODES = frozenset({'missing_glyph', 'banned_word', 'too_long', 'invented_offer', 'empty_field'})
LAYOUT_CODES = frozenset({'layout_invalid', 'layout_rule', 'text_too_small'})


@cache
def load_prompt(name: str) -> str:
    """prompts/{name}.md 的內容（系統指示）"""
    return (PROMPTS_DIR / f'{name}.md').read_text(encoding='utf-8')


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def shorten(text: str, n: int) -> str:
    text = text.strip()
    return text[:n] + '…' if len(text) > n else text


class BriefRun:
    """需求拆解（api）沒有任務：不檢查取消，log 寫到 logger。"""

    job_id = ''

    async def emit(self, event: JobEvent) -> None:
        return None

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        logger.log(logging.WARNING if level in ('warn', 'error') else logging.INFO, '%s: %s', source, message)

    async def pace(self, ms: float) -> None:
        return None

    async def wait(self, awaitable: Awaitable[T], note: str | None = None) -> T:
        return await awaitable


def guard_brief(draft: BriefDraft, text: str, product: Product | None) -> ParsedBrief:
    """需求拆解的護欄：商品名稱取自商品資料、賣點為空時用商品特色、需求沒有數字時不填期間、風格只留英文單字。"""
    style: list[str] = []
    for word in draft.style:
        w = word.strip().lower()
        if re.fullmatch(r'[a-z]+', w) and w not in style:
            style.append(w)
    points = [p.strip() for p in draft.selling_points if p.strip()]
    return ParsedBrief(
        product_name=product.name if product else None,
        selling_points=points or (product.features[:3] if product else []),
        audience=draft.audience.strip(),
        tone=draft.tone,
        campaign=(draft.campaign or '').strip() or None,
        offer=(draft.offer or '').strip() or None,
        period=(draft.period or '').strip() or None if re.search(r'\d', text) else None,
        style=style,
    )


def guard_action(issue: GuardIssue) -> str:
    """第二次仍有問題時，程式的處理方式（warn log 的結尾）"""
    if issue.code in COPY_CODES:
        return '已改用預設文案'
    if issue.code in LAYOUT_CODES:
        return '已改用預設版型'
    if issue.code == 'prompt_invalid':
        return '已改用預設提示詞' if issue.field == 'scene' else '已捨棄'
    if issue.code == 'emoji_removed':
        return '已移除'
    return '保留原文'


def product_image_size(settings: Settings, product: Product) -> tuple[int, int] | None:
    """商品圖的尺寸：去背完成時取不透明區域的外框，否則為照片（依 EXIF 轉正）；示範商品為向量素材的尺寸。
    讀不到時為 None（提示詞不提供長寬比）。"""
    if product.photo.source == 'sample':
        return SAMPLE_ART_SIZE
    cut = product.cutout
    url = cut.url if cut is not None and cut.status == 'done' and cut.url else product.photo.url
    path = resolve_url(settings, url)
    if path is None:
        return None
    try:
        with Image.open(io.BytesIO(path.read_bytes())) as img:
            upright = ImageOps.exif_transpose(img)
            if url != product.photo.url and 'A' in upright.getbands():
                box = upright.getchannel('A').getbbox()
                if box:
                    return box[2] - box[0], box[3] - box[1]
            return upright.size
    except (OSError, ValueError, Image.DecompressionBombError):
        logger.warning('讀不到商品圖，提示詞不提供長寬比：%s', url, exc_info=True)
        return None


class GeminiAgent(Agent):
    def __init__(self, client: LlmClient, composer: ComposerClient, settings: Settings) -> None:
        self.client = client
        self.composer = composer
        self.settings = settings

    # ---------- 需求拆解 ----------

    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief:
        payload = {
            'brand': {
                'name': brand.name,
                'category': brand.category,
                'defaultTone': brand.default_tone,
                'tones': TONE_NOTES,
            },
            'product': {'name': product.name, 'features': product.features} if product else None,
            'request': text,
        }
        call = GeminiCall(
            kind='brief',
            model=self.settings.gemini_llm_model,
            system=load_prompt('brief'),
            parts=[json_text(payload)],
            schema=BriefDraft,
            scope=UsageScope(job_id=None, brand_id=brand.id, round=None, target=None),
        )
        draft = await self.client.generate(call, BriefRun())
        return guard_brief(draft, text, product)

    # ---------- Prompt 構建 ----------

    async def build_spec(self, request: SpecRequest, run: RunContext) -> PromptSpec:
        template = request.template
        payload = await self._spec_payload(request)
        call = GeminiCall(
            kind='spec',
            model=self.settings.gemini_llm_model,
            system=load_prompt('spec'),
            parts=[json_text(payload)],
            schema=SpecDraft,
            scope=UsageScope(job_id=request.job_id, brand_id=request.brand.id, round=request.round, target=template.id),
            seed=request.seed,
        )
        draft = await self.client.generate(call, run)
        spec, issues = await self.composer.spec(draft, request)
        retry = [i for i in issues if i.retry]
        if retry:
            await run.log('agent', f'{template.label}：護欄發現 {len(retry)} 個問題，請 Gemini 修正一次')
            problems = '\n'.join(f'- {i.message}' for i in retry)
            again = GeminiCall(
                kind='spec',
                model=call.model,
                system=call.system,
                parts=[
                    *call.parts,
                    f'你上一次的輸出：\n{json_text(draft.to_json())}',
                    f'程式檢查發現以下問題，請修正後重新輸出完整的 JSON：\n{problems}',
                ],
                schema=SpecDraft,
                scope=call.scope,
                seed=call.seed,
            )
            draft = await self.client.generate(again, run)
            spec, issues = await self.composer.spec(draft, request)
        # 最後採用的結果：仍有問題的欄位已改用預設（retry），或程式直接處理（emoji、商品名稱的缺字）
        for issue in issues:
            await run.log('agent', f'護欄：{issue.message}，{guard_action(issue)}', 'warn')
        if draft.rationale.strip():
            await run.log('agent', f'{template.label}：{shorten(draft.rationale, RATIONALE_CHARS)}')
        return spec

    async def _spec_payload(self, request: SpecRequest) -> dict[str, Any]:
        brand, product, template = request.brand, request.product, request.template
        default_layout = await self.composer.layout(template.id)
        size = await asyncio.to_thread(product_image_size, self.settings, product)
        tone = request.brief.tone
        previous = request.previous
        return {
            'brand': {
                'name': brand.name,
                'category': brand.category,
                'palette': brand.palette.to_json(),
                'fonts': brand.fonts.to_json(),
                'visualStyle': brand.visual_style,
                'tone': tone,
                'toneExample': brand.copy_presets[tone].to_json(),
                'bannedWords': brand.banned_words,
                'replacements': brand.replacements,
                'claimWords': brand.claim_words,
                'disclaimerPhrase': brand.disclaimer_phrase,
            },
            'product': {
                'name': product.name,
                'features': product.features,
                'price': product.price.to_json(),
                'image': {'width': size[0], 'height': size[1], 'aspect': round(size[0] / size[1], 3)} if size else None,
            },
            'brief': {'text': request.text, 'parsed': request.brief.to_json()},
            'template': {
                'id': template.id,
                'label': template.label,
                'width': template.width,
                'height': template.height,
                'ratio': template.ratio,
                'defaultLayout': [{'id': b.id, 'bbox': list(b.bbox)} for b in default_layout],
            },
            'guidelines': [{'id': h.chunk_id, 'section': h.section, 'text': h.text} for h in request.hits],
            'previous': {
                'copy': previous.spec.copy_.to_json(),
                'layout': [{'id': b.id, 'bbox': list(b.bbox)} for b in previous.spec.layout],
                'failedChecks': [
                    {'id': c.id, 'name': c.name, 'rule': c.rule, 'value': c.value, 'status': c.status}
                    for c in previous.checks
                    if c.status != 'pass'
                ],
                'fixes': [f.to_json() for f in previous.fixes],
            }
            if previous
            else None,
            'limits': {
                'copy': COPY_LIMITS,
                'layout': {
                    'productRatio': list(brand.rules.product_ratio),
                    'minWhitespace': brand.rules.min_whitespace,
                    'logoClearance': 'Logo 框下緣到標題框上緣 ≥ 0.5 × Logo 框高',
                },
            },
        }

    # ---------- Query Rewriting ----------

    async def plan_rewrite(
        self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck], run: RunContext, *, retries_left: int
    ) -> Rewrite:
        failing = [c for c in checks if c.status != 'pass']
        cited = {c.rag_ref for c in failing if c.rag_ref}
        payload = {
            'brand': {
                'name': brand.name,
                'category': brand.category,
                'bannedWords': brand.banned_words,
                'replacements': brand.replacements,
            },
            'round': spec.round,
            'retriesLeft': retries_left,
            'failedChecks': [
                {'id': c.id, 'name': c.name, 'rule': c.rule, 'value': c.value, 'status': c.status, 'target': c.target}
                for c in failing
            ],
            'guidelines': [
                {'id': c.id, 'section': c.section, 'text': c.text} for c in brand.guideline_chunks if c.id in cited
            ],
            'copy': spec.copy_.to_json(),
            'layout': [{'id': b.id, 'bbox': list(b.bbox)} for b in spec.layout],
        }
        call = GeminiCall(
            kind='rewrite',
            model=self.settings.gemini_llm_model,
            system=load_prompt('rewrite'),
            parts=[json_text(payload)],
            schema=RewriteDraft,
            scope=UsageScope(job_id=run.job_id, brand_id=brand.id, round=spec.round, target=spec.template_id),
            seed=None,
        )
        draft = await self.client.generate(call, run)
        return await self._guard_rewrite(draft, brand, spec, failing)

    async def _guard_rewrite(
        self, draft: RewriteDraft, brand: Brand, spec: PromptSpec, failing: list[ReviewCheck]
    ) -> Rewrite:
        """Query Rewriting 的護欄：只留未通過檢查的修正、同一檢查合併為一個、缺少的以 planFixes 逐項補上；
        禁用詞或誇大用語未通過時一定重新檢索。"""
        failing_ids = list(dict.fromkeys(c.id for c in failing))
        by_check: dict[CheckId, Fix] = {}
        for f in draft.fixes:
            title, desc = shorten(f.title, FIX_TITLE_CHARS), shorten(f.desc, FIX_DESC_CHARS)
            if f.check_id not in failing_ids or not title or not desc:
                continue
            known = by_check.get(f.check_id)
            by_check[f.check_id] = (
                known.model_copy(update={'desc': f'{known.desc}；{desc}'})
                if known
                else Fix(check_id=f.check_id, title=title, desc=desc)
            )
        missing = [c for c in failing if c.id not in by_check]
        planned = await asyncio.gather(*(self.composer.fixes([c], brand, spec) for c in missing))
        for c, fixes in zip(missing, planned, strict=True):
            if fixes:
                by_check.setdefault(c.id, fixes[0].model_copy(update={'check_id': c.id}))
        query = (draft.requery or '').strip() or None
        if query is None and REQUERY_CHECKS & set(failing_ids):
            query = f'{brand.category} 禁用詞 合規替代用語'
        return Rewrite(fixes=[by_check[i] for i in failing_ids if i in by_check], query=query)
