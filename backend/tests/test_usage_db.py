"""job_usage：寫入、加總與上限（需要資料庫）。"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import JobInput
from app.db.models import JobRow
from app.db.session import Database
from app.errors import BudgetExceeded
from app.repo import jobs
from app.settings import REPO_ROOT
from app.usage import Pricing, PricingError, TokenUsage, UsageLedger, UsageScope
from tests.fixtures import load_fixture

PRICING = Pricing.load(REPO_ROOT / 'pricing.yaml')
NOW = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)
MODEL = 'gemini-3.8-flash'
#: 1,000,000 個輸出 tokens：目前單價 US$3.75
MILLION_OUT = TokenUsage(input_tokens=0, cached_tokens=0, output_tokens=1_000_000, thinking_tokens=400_000)


def job_scope(job_id: str | None = 'job_u', round: int | None = 1, target: str | None = 'ig-post') -> UsageScope:
    return UsageScope(job_id=job_id, brand_id='selune', round=round, target=target)


def ledger(db: Database, *, job: float = 1, monthly: float = 20, now: datetime = NOW) -> UsageLedger:
    return UsageLedger(db, PRICING, job_budget=job, monthly_budget=monthly, clock=lambda: now)


async def create_job(session: AsyncSession, job_id: str = 'job_u') -> None:
    data = load_fixture('timelines/selune-retry.json')
    await jobs.create_job(session, job_id, JobInput.model_validate(data['input']), NOW)


async def test_records_usage_with_the_price_at_the_time(db: Database, session: AsyncSession) -> None:
    await create_job(session)
    usage = TokenUsage(input_tokens=4120, cached_tokens=1000, output_tokens=1032, thinking_tokens=640)
    assert await ledger(db).record(job_scope(), 'spec', 'gemini-3.8-flash', usage) == Decimal('0.006960')
    after = ledger(db, now=datetime(2027, 1, 2, tzinfo=UTC))
    assert await after.record(job_scope(), 'vlm', 'gemini-3.8-flash', usage) == Decimal('0.013920')
    assert await after.job_summary('job_u') == (Decimal('0.020880'), 2)
    assert await ledger(db).job_summary('job_other') == (Decimal('0'), 0)


async def test_the_job_budget_stops_the_next_call(db: Database, session: AsyncSession) -> None:
    await create_job(session)
    book = ledger(db, job=1)
    await book.check(job_scope(), MODEL)
    await book.record(job_scope(), 'spec', 'gemini-3.8-flash', TokenUsage(0, 0, 136_000, 0))
    await book.check(job_scope(), MODEL)
    await book.record(job_scope(), 'spec', 'gemini-3.8-flash', TokenUsage(0, 0, 136_000, 0))
    with pytest.raises(BudgetExceeded, match=r'^已達單一任務的 Gemini 費用上限（US\$1\.00，已用 US\$1\.02）$'):
        await book.check(job_scope(), MODEL)
    # 其他任務與需求拆解不受影響
    await book.check(job_scope(job_id='job_other'), MODEL)
    await book.check(job_scope(job_id=None, round=None, target=None), MODEL)


async def test_the_monthly_budget_counts_taipei_months_including_briefs(db: Database, session: AsyncSession) -> None:
    await create_job(session)
    october = ledger(db, monthly=5, now=datetime(2026, 10, 31, 15, 0, tzinfo=UTC))
    await october.record(job_scope(job_id=None, round=None, target=None), 'brief', 'gemini-3.8-flash', MILLION_OUT)
    await october.record(job_scope(), 'spec', 'gemini-3.8-flash', MILLION_OUT)
    assert await october.month_total() == Decimal('7.500000')
    with pytest.raises(BudgetExceeded, match=r'^本月 Gemini 費用已達上限（US\$5\.00）$'):
        await october.check(job_scope(job_id=None, round=None, target=None), MODEL)
    # 台北時間 11/01 00:30：上個月的紀錄不算
    november = ledger(db, monthly=5, now=datetime(2026, 10, 31, 16, 30, tzinfo=UTC))
    assert await november.month_total() == Decimal('0')
    # 以需求拆解的範圍檢查：這個任務在 10 月已用 US$3.75，會先碰到單一任務的上限
    await november.check(job_scope(job_id=None, round=None, target=None), MODEL)


async def test_models_without_a_price_are_refused_before_calling(db: Database, session: AsyncSession) -> None:
    with pytest.raises(PricingError, match='沒有 gemini-x 的單價'):
        await ledger(db).check(job_scope(), 'gemini-x')
    broken = UsageLedger(db, Pricing({}, problem='找不到單價表：/app/pricing.yaml'), job_budget=1, monthly_budget=20)
    with pytest.raises(PricingError, match='找不到單價表'):
        await broken.check(job_scope(), MODEL)


async def test_zero_budgets_mean_no_limit(db: Database, session: AsyncSession) -> None:
    await create_job(session)
    book = ledger(db, job=0, monthly=0)
    for _ in range(3):
        await book.record(job_scope(), 'spec', 'gemini-3.8-flash', MILLION_OUT)
    await book.check(job_scope(), MODEL)


async def test_usage_is_deleted_with_its_job_and_summed_per_job(db: Database, session: AsyncSession) -> None:
    await create_job(session, 'job_a')
    await create_job(session, 'job_b')
    book = ledger(db)
    await book.record(job_scope('job_a'), 'spec', 'gemini-3.8-flash', MILLION_OUT)
    await book.record(job_scope('job_a'), 'vlm', 'gemini-3.8-flash', MILLION_OUT)
    await book.record(job_scope('job_b'), 'spec', 'gemini-3.8-flash', MILLION_OUT)
    assert await book.costs_by_job(['job_a', 'job_b', 'job_c']) == {'job_a': 7.5, 'job_b': 3.75}
    await session.execute(delete(JobRow).where(JobRow.id == 'job_a'))
    await session.commit()
    assert await book.costs_by_job(['job_a', 'job_b']) == {'job_b': 3.75}
