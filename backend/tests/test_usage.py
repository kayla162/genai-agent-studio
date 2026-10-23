"""單價表、費用計算與台北時間的月份（不需要資料庫）。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.errors import AppError
from app.settings import REPO_ROOT
from app.usage import Price, Pricing, PricingError, cost_usd, month_bounds

PRICING = Pricing.load(REPO_ROOT / 'pricing.yaml')


def test_the_repo_pricing_doubles_on_2027_01_01_taipei_time() -> None:
    assert PRICING.has('gemini-3.8-flash')
    before = PRICING.price('gemini-3.8-flash', datetime(2026, 12, 31, 15, 59, tzinfo=UTC))
    after = PRICING.price('gemini-3.8-flash', datetime(2026, 12, 31, 16, 0, tzinfo=UTC))
    assert (before.from_, before.input, before.output, before.cached_input) == (date(2026, 1, 1), 0.75, 3.75, None)
    assert (after.from_, after.input, after.output) == (date(2027, 1, 1), 1.5, 7.5)


def test_unknown_models_and_dates_before_any_price_are_errors() -> None:
    assert not PRICING.has('gemini-x')
    with pytest.raises(PricingError, match='pricing.yaml 沒有 gemini-x 的單價'):
        PRICING.price('gemini-x', datetime(2026, 10, 23, tzinfo=UTC))
    with pytest.raises(PricingError, match='還沒有生效的單價'):
        PRICING.price('gemini-3.8-flash', datetime(2025, 12, 31, tzinfo=UTC))
    assert issubclass(PricingError, AppError)


def test_broken_pricing_files_are_reported_in_chinese(tmp_path: Path) -> None:
    missing = tmp_path / 'missing.yaml'
    with pytest.raises(PricingError, match='找不到單價表'):
        Pricing.load(missing)
    broken = tmp_path / 'broken.yaml'
    broken.write_text('gemini-3.8-flash:\n  - {from: 2026-01-01, input: abc, output: 3.75}\n', encoding='utf-8')
    with pytest.raises(PricingError, match='單價表格式錯誤'):
        Pricing.load(broken)
    not_yaml = tmp_path / 'not-yaml.yaml'
    not_yaml.write_text('gemini: [', encoding='utf-8')
    with pytest.raises(PricingError, match='單價表格式錯誤'):
        Pricing.load(not_yaml)


def test_cost_uses_the_cached_input_price_when_set_and_rounds_to_six_places() -> None:
    plain = Price.model_validate({'from': '2026-01-01', 'input': 0.75, 'output': 3.75})
    # (4120 - 1000) × 0.75 + 1000 × 0.75 + 1032 × 3.75 = 6,960 → US$0.006960
    assert cost_usd(plain, input_tokens=4120, cached_tokens=1000, output_tokens=1032) == Decimal('0.006960')
    cached = Price.model_validate({'from': '2026-01-01', 'input': 0.75, 'output': 3.75, 'cachedInput': 0.1875})
    # 3120 × 0.75 + 1000 × 0.1875 + 1032 × 3.75 = 6,397.5 → US$0.0063975 → 0.006398
    assert cost_usd(cached, input_tokens=4120, cached_tokens=1000, output_tokens=1032) == Decimal('0.006398')
    assert cost_usd(plain, input_tokens=0, cached_tokens=0, output_tokens=0) == Decimal('0.000000')


def test_months_follow_taipei_time() -> None:
    start, end = month_bounds(datetime(2026, 10, 31, 16, 30, tzinfo=UTC))
    assert (start, end) == (datetime(2026, 10, 31, 16, 0, tzinfo=UTC), datetime(2026, 11, 30, 16, 0, tzinfo=UTC))
    start, end = month_bounds(datetime(2026, 12, 15, tzinfo=UTC))
    assert (start, end) == (datetime(2026, 11, 30, 16, 0, tzinfo=UTC), datetime(2026, 12, 31, 16, 0, tzinfo=UTC))
