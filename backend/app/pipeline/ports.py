"""任務流程依賴的外部服務介面。每個介面都有真實版與模擬版（app/pipeline/sim.py），由設定切換。"""

from dataclasses import dataclass
from typing import Protocol

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
    ParsedBrief,
    Product,
    PromptSpec,
    RagHit,
    Render,
    RenderBackground,
    ReviewCheck,
    TemplateId,
)


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
    """任務執行中可用的動作（ImageEngine 回報進度用）。"""

    async def emit(self, event: JobEvent) -> None: ...

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None: ...

    async def pace(self, ms: float) -> None: ...


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

    async def build_spec(self, request: SpecRequest) -> PromptSpec: ...

    async def plan_rewrite(self, brand: Brand, spec: PromptSpec, checks: list[ReviewCheck]) -> Rewrite: ...


class ImageEngine(Protocol):
    async def render_round(
        self, job_id: str, round: int, specs: list[PromptSpec], variants: int, brand: Brand, run: RunContext
    ) -> dict[tuple[TemplateId, int], RenderBackground]: ...


class Reviewer(Protocol):
    async def review(self, brand: Brand, render: Render, seed: int) -> ReviewResult: ...


@dataclass(frozen=True)
class Ports:
    retriever: Retriever
    agent: Agent
    image: ImageEngine
    reviewer: Reviewer
