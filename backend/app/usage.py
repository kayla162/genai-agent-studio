"""Gemini 的用量與費用：單價表（repo 根目錄的 pricing.yaml）、費用計算、job_usage 的寫入與加總、費用上限。

- 每個有回應的 Gemini 請求寫一筆 job_usage；費用依寫入時的單價計算，之後單價改變也不影響舊紀錄。
- 上限只在 AGENT_MODE=gemini 時使用：每次呼叫前加總該任務與台北時間當月的費用，達到上限時不送出。
  上限在呼叫前檢查，最多超出並行中的呼叫的費用。上限為 0 時不檢查。
- 免費方案實際不收費，但這裡仍依付費單價記錄，上限照樣生效。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from app.core.clock import utc_now
from app.db.models import JobUsageRow
from app.db.session import Database
from app.errors import BudgetExceeded, Unavailable
from app.repo import usage as repo

#: 單價的生效日與每月上限都以台北時間計算
PRICING_TZ = ZoneInfo('Asia/Taipei')
#: 每百萬 tokens
PER_TOKENS = Decimal(1_000_000)
COST_PLACES = Decimal('0.000001')

#: Gemini 呼叫的種類：需求拆解、Prompt 構建、Query Rewriting、VLM 審查
UsageKind = Literal['brief', 'spec', 'rewrite', 'vlm']


class PricingError(Unavailable):
    """單價表讀不到、格式錯誤，或沒有設定使用的模型：沒有單價就無法套用上限，所有 Gemini 呼叫都被拒絕。"""


class Price(BaseModel):
    """一筆單價（美元／每百萬 tokens）；from 為生效日（台北時間）。cachedInput 省略時與 input 相同（保守估計）。"""

    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    from_: date = Field(alias='from')
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cached_input: float | None = Field(default=None, ge=0, alias='cachedInput')


class _PricingFile(RootModel[dict[str, list[Price]]]):
    pass


class Pricing:
    def __init__(self, table: dict[str, list[Price]], source: str = 'pricing.yaml', problem: str | None = None) -> None:
        self.source = source
        #: 單價表讀不到或格式錯誤時的原因（load_or_unavailable）；這時所有呼叫都被拒絕
        self.problem = problem
        self._table = {model: sorted(prices, key=lambda p: p.from_) for model, prices in table.items()}

    @classmethod
    def load_or_unavailable(cls, path: Path) -> 'Pricing':
        """與 load 相同，但讀不到或格式錯誤時不丟出例外：回傳沒有任何單價的表，原因記在 problem
        （api 與 worker 照常啟動，系統狀態顯示原因，Gemini 呼叫一律被拒絕）。"""
        try:
            return cls.load(path)
        except PricingError as error:
            return cls({}, path.name, problem=error.message)

    @classmethod
    def load(cls, path: Path) -> 'Pricing':
        if not path.is_file():
            raise PricingError(f'找不到單價表：{path}')
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            table = _PricingFile.model_validate(data).root
        except (yaml.YAMLError, ValidationError, UnicodeDecodeError) as error:
            raise PricingError(f'單價表格式錯誤（{path.name}）：{_first_problem(error)}') from error
        return cls(table, path.name)

    def has(self, model: str) -> bool:
        return bool(self._table.get(model))

    def price(self, model: str, at: datetime) -> Price:
        """at（台北時間）當天已生效的最新一筆單價。"""
        if self.problem is not None:
            raise PricingError(self.problem)
        prices = self._table.get(model)
        if not prices:
            raise PricingError(f'{self.source} 沒有 {model} 的單價，無法計算費用與套用上限')
        day = at.astimezone(PRICING_TZ).date()
        effective = [p for p in prices if p.from_ <= day]
        if not effective:
            raise PricingError(f'{self.source} 的 {model} 在 {day} 還沒有生效的單價')
        return effective[-1]


def _first_problem(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return f'{".".join(str(p) for p in first["loc"])}：{first["msg"]}'
    return str(error).splitlines()[0]


def cost_usd(price: Price, input_tokens: int, cached_tokens: int, output_tokens: int) -> Decimal:
    """［（輸入 − 快取）× input ＋ 快取 × cachedInput ＋ 輸出 × output］÷ 1,000,000，四捨五入到小數 6 位。"""
    cached_rate = price.input if price.cached_input is None else price.cached_input
    total = (
        Decimal(input_tokens - cached_tokens) * Decimal(str(price.input))
        + Decimal(cached_tokens) * Decimal(str(cached_rate))
        + Decimal(output_tokens) * Decimal(str(price.output))
    )
    return (total / PER_TOKENS).quantize(COST_PLACES, rounding=ROUND_HALF_UP)


def month_bounds(now: datetime, tz: ZoneInfo = PRICING_TZ) -> tuple[datetime, datetime]:
    """now 所在的月份（tz 的時間）：開始與結束（不含），轉成 UTC。"""
    local = now.astimezone(tz)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.astimezone(ZoneInfo('UTC')), end.astimezone(ZoneInfo('UTC'))


def usd(amount: Decimal | float) -> str:
    """US$1.23"""
    return f'US${Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}'


@dataclass(frozen=True)
class UsageScope:
    """一次呼叫屬於哪個任務、品牌、輪次與目標（模板 id 或候選 id）；需求拆解沒有任務。"""

    job_id: str | None
    brand_id: str
    round: int | None
    target: str | None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    #: 輸入中命中隱式快取的部分
    cached_tokens: int
    #: 包含思考
    output_tokens: int
    thinking_tokens: int


class UsageRecorder(Protocol):
    async def check(self, scope: UsageScope, model: str) -> None:
        """呼叫前檢查：model 有單價（否則丟出 PricingError），且還沒達到上限（否則丟出 BudgetExceeded）。"""
        ...

    async def record(self, scope: UsageScope, kind: UsageKind, model: str, usage: TokenUsage) -> Decimal:
        """寫入一筆用量並回傳費用。"""
        ...


class UsageLedger(UsageRecorder):
    """以 job_usage 資料表記錄用量、加總費用與檢查上限。"""

    def __init__(
        self,
        db: Database,
        pricing: Pricing,
        *,
        job_budget: float,
        monthly_budget: float,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.pricing = pricing
        self.job_budget = Decimal(str(job_budget))
        self.monthly_budget = Decimal(str(monthly_budget))
        self.clock = clock

    async def check(self, scope: UsageScope, model: str) -> None:
        # 沒有單價就無法計算費用與套用上限：不送出
        self.pricing.price(model, self.clock())
        if self.monthly_budget > 0 and await self.month_total() >= self.monthly_budget:
            raise BudgetExceeded(f'本月 Gemini 費用已達上限（{usd(self.monthly_budget)}）')
        if self.job_budget > 0 and scope.job_id is not None:
            spent, _ = await self.job_summary(scope.job_id)
            if spent >= self.job_budget:
                raise BudgetExceeded(f'已達單一任務的 Gemini 費用上限（{usd(self.job_budget)}，已用 {usd(spent)}）')

    async def record(self, scope: UsageScope, kind: UsageKind, model: str, usage: TokenUsage) -> Decimal:
        now = self.clock()
        cost = cost_usd(self.pricing.price(model, now), usage.input_tokens, usage.cached_tokens, usage.output_tokens)
        row = JobUsageRow(
            job_id=scope.job_id,
            brand_id=scope.brand_id,
            created_at=now,
            provider='gemini',
            model=model,
            kind=kind,
            round=scope.round,
            target=scope.target,
            input_tokens=usage.input_tokens,
            cached_tokens=usage.cached_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=usage.thinking_tokens,
            seconds=None,
            cost_usd=cost,
        )
        async with self.db.session() as s:
            await repo.add_usage(s, row)
        return cost

    async def month_total(self) -> Decimal:
        start, end = month_bounds(self.clock())
        async with self.db.session() as s:
            return await repo.range_total(s, start, end)

    async def job_summary(self, job_id: str) -> tuple[Decimal, int]:
        async with self.db.session() as s:
            return await repo.job_total(s, job_id)

    async def costs_by_job(self, job_ids: list[str]) -> dict[str, float]:
        async with self.db.session() as s:
            return {job_id: float(total) for job_id, total in (await repo.costs_by_job(s, job_ids)).items()}
