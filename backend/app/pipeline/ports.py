"""任務流程依賴的外部服務介面。每個介面都有真實版與模擬版（app/pipeline/sim.py），由設定切換。"""

from collections.abc import Awaitable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, TypeVar

from app.contract import (
    Brand,
    ChannelTemplate,
    CheckId,
    Engine,
    Fix,
    JobEvent,
    JobInput,
    LogLevel,
    LogSource,
    Model,
    ParsedBrief,
    Product,
    PromptSpec,
    RagHit,
    Render,
    RenderBackground,
    ReviewCheck,
    TemplateId,
)

T = TypeVar('T')


class JobCancelled(Exception):
    """使用者取消了任務：runner 停下來並送出 job.status cancelled。"""


@dataclass(frozen=True)
class PreviousRound:
    """某個模板上一輪最高分候選的 spec、檢查結果與 Query Rewriting 的修正項（下一輪的 Prompt 構建參考）。"""

    spec: PromptSpec
    checks: list[ReviewCheck]
    fixes: list[Fix]


@dataclass(frozen=True)
class SpecRequest:
    job_id: str
    round: int
    brand: Brand
    product: Product
    brief: ParsedBrief
    template: ChannelTemplate
    engine: Engine
    seed: int
    rag_refs: list[str]
    #: 之前各輪未通過的檢查（依出現順序，不重複）
    fixes: list[CheckId]
    #: 使用者的一句話需求
    text: str = ''
    #: rag_refs 對應的切塊全文（Rerank 後前 5 筆，加上重新檢索的切塊）；Gemini 的提示詞只放這些
    hits: list[RagHit] = field(default_factory=list)
    #: 這個模板上一輪的結果；第一輪為 None
    previous: PreviousRound | None = None


@dataclass(frozen=True)
class Rewrite:
    fixes: list[Fix]
    #: 需要重新檢索合規用語時的查詢；不需要時為 None
    query: str | None


@dataclass(frozen=True)
class ReviewResult:
    checks: list[ReviewCheck]
    score: int
    passed: bool


class RunContext(Protocol):
    """任務執行中可用的動作：送出事件與 log、依時間軸等待、可取消的等待。"""

    job_id: str

    async def emit(self, event: JobEvent) -> None: ...

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None: ...

    async def pace(self, ms: float) -> None: ...

    async def wait(self, awaitable: Awaitable[T], note: str | None = None) -> T:
        """等待 awaitable，期間每 0.5 秒檢查取消旗標。取消時中斷 awaitable，note 有值時先寫一則 warn log，
        再丟出 JobCancelled（例如等待 Gemini 回應時：已中斷的呼叫可能仍會計費）。"""
        ...


class Retriever(Protocol):
    async def retrieve(
        self, brand: Brand, product: Product, job_input: JobInput, run: RunContext
    ) -> tuple[str, list[RagHit]]:
        """回傳查詢字串與召回的切塊。run 用來在等候模型準備時送出 log。"""
        ...

    async def rerank(self, query: str, hits: list[RagHit]) -> list[RagHit]: ...

    async def requery(self, brand: Brand, query: str) -> list[RagHit]: ...


class Agent(Protocol):
    async def parse_brief(self, brand: Brand, text: str, product: Product | None) -> ParsedBrief: ...

    async def build_spec(self, request: SpecRequest, run: RunContext) -> PromptSpec: ...

    async def plan_rewrite(
        self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck], run: RunContext, *, retries_left: int
    ) -> Rewrite:
        """checks 為某個模板最高分候選的檢查結果；retries_left 為含這次在內還剩幾次重試。"""
        ...


class ImageEngine(Protocol):
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
        """一輪的生圖：每個模板 × variant 一張背景。product 給 ComfyUI 的商品底圖用（模擬版不使用）。"""
        ...

    async def finish(self, job_id: str) -> None:
        """任務結束（完成、失敗或取消）時收尾，例如請 ComfyUI 釋放記憶體；不丟出例外。"""
        ...


class BackgroundPalette(Model):
    """composer 從疊上文字與商品之前的背景量到的品牌色系（web/src/lib/review/background.ts，/render 的
    X-Background-Palette 標頭），worker 原樣送回 /review。"""

    #: 商品方框以外、品牌色系外的像素比例（0–1）
    off_share: float
    #: 色系外像素中最多的顏色（大寫 #RRGGBB）；沒有色系外的像素時為 None
    off_hex: str | None
    #: 量測的像素數
    sampled: int


@dataclass(frozen=True)
class ComposedPoster:
    """伺服器端繪製的審查用海報。"""

    #: 審查用海報的網址（/files/jobs/{jobId}/{renderId}.png）
    url: str
    #: 從海報像素量到的品牌主色（小寫 #rrggbb）；量不到時為 None
    measured_primary: str | None
    #: 背景的品牌色系；composer 沒有回傳時為 None（背景色系判定為模擬）
    background: BackgroundPalette | None = None


class PosterComposer(Protocol):
    async def compose(self, job_id: str, render: Render, product: Product, brand: Brand) -> ComposedPoster | None:
        """繪製一張候選的審查用海報並存檔；模擬版不畫圖，回傳 None。"""
        ...


class Reviewer(Protocol):
    async def review(
        self, brand: Brand, render: Render, seed: int, poster: ComposedPoster | None, run: RunContext
    ) -> ReviewResult:
        """poster 是排版階段繪製的審查用海報（模擬版為 None）。"""
        ...


class UsageReport(Protocol):
    async def job_summary(self, job_id: str) -> tuple[Decimal, int]:
        """一個任務的外部服務費用合計（美元）與呼叫次數。"""
        ...


@dataclass(frozen=True)
class Ports:
    retriever: Retriever
    agent: Agent
    image: ImageEngine
    posters: PosterComposer
    reviewer: Reviewer
    #: 用量與費用（AGENT_MODE=gemini）；模擬模式為 None，不送出費用合計
    usage: UsageReport | None = None
