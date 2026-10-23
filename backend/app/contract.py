"""前後端資料約定：對應 web/src/types/contract.ts（欄位名稱、型別、選填規則都必須一致）。

JSON 一律使用 camelCase（以 alias 產生），Python 端使用 snake_case。
WebSocket 送出的訊息是事件加上 seq 與 ts（見 message_json）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_serializer
from pydantic.alias_generators import to_camel

TemplateId = Literal['ecom-main', 'scene', 'ig-post', 'story', 'banner']
TEMPLATE_IDS: tuple[TemplateId, ...] = ('ecom-main', 'scene', 'ig-post', 'story', 'banner')
LayoutElementId = Literal['logo', 'headline', 'subhead', 'features', 'product', 'badge', 'price', 'disclaimer']
CheckId = Literal[
    'banned_words',
    'color_delta',
    'bg_palette',
    'logo_clearance',
    'disclaimer',
    'product_ratio',
    'whitespace',
    'ocr_typo',
    'vlm_exaggeration',
    'vlm_occlusion',
    'vlm_quality',
]
CHECK_IDS: tuple[CheckId, ...] = (
    'banned_words',
    'color_delta',
    'bg_palette',
    'logo_clearance',
    'disclaimer',
    'product_ratio',
    'whitespace',
    'ocr_typo',
    'vlm_exaggeration',
    'vlm_occlusion',
    'vlm_quality',
)
Tone = Literal['gentle', 'science', 'playful', 'minimal']
Engine = Literal['comfyui', 'ideogram']
RagTag = Literal['color', 'logo', 'law', 'layout', 'font', 'history', 'general']
JobStage = Literal[
    'queued',
    'parsing',
    'retrieving',
    'prompting',
    'rendering',
    'composing',
    'reviewing',
    'rewriting',
    'saving',
    'done',
    'needs_review',
    'cancelled',
    'failed',
]
FINISHED_STAGES: frozenset[JobStage] = frozenset({'done', 'needs_review', 'cancelled', 'failed'})
RenderNode = Literal['cutout', 'generate', 'relight', 'upscale']
LogSource = Literal['ws', 'api', 'agent', 'rag', 'comfy', 'compose', 'vlm', 'db']
LogLevel = Literal['info', 'ok', 'warn', 'error']
CheckStatus = Literal['pass', 'warn', 'fail']
BBox = tuple[int, int, int, int]


class Model(BaseModel):
    """所有約定模型的基底：camelCase JSON、拒絕多餘欄位。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra='forbid')

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode='json')


# ---------- 品牌與 RAG ----------
class Palette(Model):
    primary: str
    secondary: str
    accent: str
    ink: str


class RagChunk(Model):
    id: str
    source: str
    section: str
    tag: RagTag
    text: str


class CaseStudy(Model):
    id: str
    title: str
    channel: str
    ctr: float
    notes: str


class BrandRules(Model):
    max_delta_e: float
    min_whitespace: float
    product_ratio: tuple[float, float]


class Fonts(Model):
    headline: str
    body: str


class CopyPreset(Model):
    headline: tuple[str, str]
    subhead: str


class BrandLogo(Model):
    url: str


class Brand(Model):
    id: str
    name: str
    category: str
    ci_version: str
    palette: Palette
    fonts: Fonts
    visual_style: str
    default_tone: Tone
    rules: BrandRules
    banned_words: list[str]
    replacements: dict[str, str]
    claim_words: list[str]
    disclaimer_phrase: str
    guideline_chunks: list[RagChunk]
    case_studies: list[CaseStudy]
    copy_presets: dict[Tone, CopyPreset]
    logo: BrandLogo | None


# ---------- 商品與模板 ----------
class SamplePhoto(Model):
    source: Literal['sample']
    art: Literal['serum', 'coldbrew']


class FilePhoto(Model):
    source: Literal['upload', 'local']
    url: str


ProductPhoto = Annotated[SamplePhoto | FilePhoto, Field(discriminator='source')]


CutoutStatus = Literal['pending', 'done', 'failed']


class ProductCutout(Model):
    """去背結果：pending 去背中、done 完成（url 為透明 PNG；mock 的示意為 null）、failed 失敗（error 為原因）。"""

    model: str
    status: CutoutStatus
    url: str | None
    error: str | None


class Price(Model):
    sale: int
    original: int


class Product(Model):
    id: str
    brand_id: str
    name: str
    features: list[str]
    price: Price
    photo: ProductPhoto
    cutout: ProductCutout | None
    created_at: str


class ProductDraft(Model):
    """新增或修改商品（對應 web/src/lib/api/client.ts 的 ProductDraft：沒有 id 時新增）。"""

    id: str | None = None
    brand_id: str
    name: str
    features: list[str]
    price: Price
    photo: ProductPhoto
    cutout: ProductCutout | None


class ChannelTemplate(Model):
    id: TemplateId
    label: str
    ratio: str
    width: int
    height: int


# ---------- 任務輸入 ----------
class ParsedBrief(Model):
    product_name: str | None
    selling_points: list[str]
    audience: str
    tone: Tone
    campaign: str | None
    offer: str | None
    period: str | None
    style: list[str]


class JobInput(Model):
    brand_id: str
    product_id: str
    brief: str
    parsed_brief: ParsedBrief
    template_ids: list[TemplateId]
    variants_per_template: int
    llm: str
    engine: Engine
    vlm: str
    max_retries: int


class DemoOptions(Model):
    speed: Literal[1, 2, 4]
    first_round_fail: bool
    force_all_fail: bool


# ---------- Agent 輸出 ----------
class Badge(Model):
    top: str
    main: str
    sub: str


class CopyPrice(Model):
    label: str
    sale: int
    original: int


class Copy(Model):
    headline: tuple[str, str]
    subhead: str
    features: list[str]
    badge: Badge
    price: CopyPrice
    product_name: str
    disclaimer: str


class ComfyParam(Model):
    node_id: str
    input: str
    label: str
    value: str | int | float


class ComfyInjection(Model):
    engine: Engine
    workflow_file: str
    params: list[ComfyParam]


class Canvas(Model):
    width: int
    height: int
    ratio: str


class LayoutBox(Model):
    id: LayoutElementId
    bbox: BBox
    z: int


class PromptSpec(Model):
    job_id: str
    round: int
    template_id: TemplateId
    brand_id: str
    canvas: Canvas
    palette: Palette
    copy_: Copy = Field(alias='copy')
    layout: list[LayoutBox]
    positive_prompt: str
    negative_prompt: str
    injection: ComfyInjection
    rag_refs: list[str]


# ---------- 審查與產出 ----------
class ReviewCheck(Model):
    id: CheckId
    name: str
    kind: Literal['rule', 'vlm']
    rule: str
    value: str
    status: CheckStatus
    target: LayoutElementId | Literal['canvas'] | None
    rag_ref: str | None


class ProceduralBackground(Model):
    kind: Literal['procedural']
    seed: int
    palette: Palette
    style: str


class UrlBackground(Model):
    kind: Literal['url']
    url: str
    includes_product: bool


RenderBackground = Annotated[ProceduralBackground | UrlBackground, Field(discriminator='kind')]


class Render(Model):
    id: str
    job_id: str
    round: int
    template_id: TemplateId
    variant: int
    background: RenderBackground
    spec: PromptSpec
    score: int | None
    passed: bool | None
    checks: list[ReviewCheck]


class RagHit(Model):
    chunk_id: str
    source: str
    section: str
    tag: RagTag
    text: str
    vector_score: float
    rerank_score: float | None = None

    @model_serializer(mode='wrap')
    def _omit_missing_rerank(self, handler: Any) -> dict[str, Any]:
        # TypeScript 的 rerankScore 是選填欄位：還沒 Rerank 時不輸出
        data: dict[str, Any] = handler(self)
        for key in ('rerankScore', 'rerank_score'):
            if key in data and data[key] is None:
                del data[key]
        return data


class Fix(Model):
    check_id: CheckId
    title: str
    desc: str


# ---------- WebSocket 事件 ----------
class JobAcceptedEvent(Model):
    type: Literal['job.accepted']
    job_id: str


class JobStatusEvent(Model):
    type: Literal['job.status']
    stage: JobStage
    round: int


class BriefParsedEvent(Model):
    type: Literal['brief.parsed']
    parsed_brief: ParsedBrief


class RagRetrievedEvent(Model):
    type: Literal['rag.retrieved']
    query: str
    hits: list[RagHit]


class RagRerankedEvent(Model):
    type: Literal['rag.reranked']
    hits: list[RagHit]


class PromptGeneratedEvent(Model):
    type: Literal['prompt.generated']
    round: int
    template_id: TemplateId
    spec: PromptSpec


class ComfyQueuedEvent(Model):
    type: Literal['comfy.queued']
    round: int
    template_id: TemplateId
    prompt_id: str
    injection: ComfyInjection


class RenderProgressEvent(Model):
    type: Literal['render.progress']
    round: int
    node: RenderNode
    step: int
    max_step: int


class RenderCompletedEvent(Model):
    type: Literal['render.completed']
    round: int
    renders: list[Render]


class ReviewCheckEvent(Model):
    type: Literal['review.check']
    round: int
    render_id: str
    check: ReviewCheck


class ReviewCompletedEvent(Model):
    type: Literal['review.completed']
    round: int
    render_id: str
    score: int
    passed: bool
    #: 審查用海報的網址（/files/jobs/{jobId}/{renderId}.png）；模擬模式與 mock 沒有繪製，為 None
    image: str | None


class RewriteStartedEvent(Model):
    type: Literal['rewrite.started']
    round: int
    template_id: TemplateId
    reasons: list[CheckId]
    fixes: list[Fix]
    requery: bool


class JobCompletedEvent(Model):
    type: Literal['job.completed']
    job_id: str
    best_render_ids: dict[TemplateId, str]


class JobNeedsReviewEvent(Model):
    type: Literal['job.needs_review']
    job_id: str
    reason: str


class JobFailedEvent(Model):
    type: Literal['job.failed']
    job_id: str
    reason: str


class LogEvent(Model):
    type: Literal['log']
    source: LogSource
    level: LogLevel
    message: str


JobEvent = Annotated[
    JobAcceptedEvent
    | JobStatusEvent
    | BriefParsedEvent
    | RagRetrievedEvent
    | RagRerankedEvent
    | PromptGeneratedEvent
    | ComfyQueuedEvent
    | RenderProgressEvent
    | RenderCompletedEvent
    | ReviewCheckEvent
    | ReviewCompletedEvent
    | RewriteStartedEvent
    | JobCompletedEvent
    | JobNeedsReviewEvent
    | JobFailedEvent
    | LogEvent,
    Field(discriminator='type'),
]
JOB_EVENT: TypeAdapter[JobEvent] = TypeAdapter(JobEvent)


def parse_event(data: dict[str, Any]) -> JobEvent:
    """事件 JSON（不含 seq、ts）→ 事件模型。"""
    return JOB_EVENT.validate_python(data)


def message_json(event: JobEvent, seq: int, ts: str) -> dict[str, Any]:
    """事件模型 → WebSocket 訊息 JSON（JobMessage：事件欄位加上 seq 與 ts）。"""
    return {**event.to_json(), 'seq': seq, 'ts': ts}


def parse_message(data: dict[str, Any]) -> tuple[JobEvent, int, str]:
    """WebSocket 訊息 JSON → (事件, seq, ts)。"""
    body = {k: v for k, v in data.items() if k not in ('seq', 'ts')}
    return parse_event(body), int(data['seq']), str(data['ts'])


# ---------- 歷史紀錄、任務列表 ----------
class HistoryEntry(Model):
    id: str
    job_id: str
    brand_id: str
    product_id: str
    input: JobInput
    template_id: TemplateId
    render: Render
    copy_: Copy = Field(alias='copy')
    selected_at: str
    favorite: bool
    written_to_rag: bool


class JobSummary(Model):
    id: str
    input: JobInput
    created_at: str
    stage: JobStage
    round: int
    finished: bool
    best_render_ids: dict[TemplateId, str]


class JobSnapshot(Model):
    """任務摘要與完整訊息（對應 web/src/lib/api/client.ts 的 JobSnapshot；訊息保持原始 JSON）。"""

    summary: JobSummary
    events: list[dict[str, Any]]


# ---------- 品牌文件上傳 ----------
class IngestChunkedEvent(Model):
    type: Literal['ingest.chunked']
    source: str
    chunks: list[RagChunk]


class IngestEmbeddedEvent(Model):
    type: Literal['ingest.embedded']
    chunk_id: str
    index: int
    total: int
    dims: int
    preview: list[float]


class IngestStoredEvent(Model):
    type: Literal['ingest.stored']
    collection: str
    count: int


IngestEvent = Annotated[IngestChunkedEvent | IngestEmbeddedEvent | IngestStoredEvent, Field(discriminator='type')]


# ---------- 成效儀表板 ----------
class CheckFailureStat(Model):
    check_id: CheckId
    name: str
    kind: Literal['rule', 'vlm']
    fail: int
    warn: int


class RerankHitStat(Model):
    k: int
    vector: float
    rerank: float


class JobStat(Model):
    job_id: str
    brand_id: str
    created_at: str
    outcome: Literal['done', 'needs_review']
    templates: int
    rounds: int
    renders: int
    delivered: int
    duration_ms: int
    cost_usd: float


class DashboardStats(Model):
    jobs: int
    renders: int
    pass_rate: float
    first_pass_rate: float
    avg_retries: float
    avg_duration_ms: float
    cost_per_image: float | None
    check_failures: list[CheckFailureStat]
    rerank_hits: list[RerankHitStat]
    recent: list[JobStat]


# ---------- 本機資料夾、可用選項與系統狀態 ----------
class LocalPhoto(Model):
    file: str
    name: str
    url: str
    size: int


class ApiOptions(Model):
    llm: list[str]
    vlm: list[str]
    engines: list[Engine]


class ComponentStatus(Model):
    id: str
    label: str
    status: Literal['ok', 'sim', 'off', 'error']
    detail: str


class SystemStatus(Model):
    components: list[ComponentStatus]
