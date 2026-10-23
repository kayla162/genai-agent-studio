"""系統狀態的 Gemini 檢查（models.get 以 respx 重播），以及品牌設定檔的缺字警告（需要 composer）。不需要資料庫。"""

import json
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.adapters.composer import ComposerClient
from app.adapters.gemini import NOT_CONFIGURED, GeminiClient
from app.api.catalog import _gemini, _probe, glyph_warnings
from app.api.services import ApiServices
from app.brands import load_brands
from app.contract import ComponentStatus
from app.db.session import Database
from app.settings import REPO_ROOT, Settings
from app.usage import Price, Pricing, UsageLedger
from tests.fixtures import BRANDS_DIR

DATA = Path(__file__).parent / 'data' / 'gemini'
KEY = 'AIza-test-key-a1B2'
MODELS = r'https://generativelanguage\.googleapis\.com/v1beta/models/'
LABEL = 'Gemini（LLM／VLM）'


def recorded(name: str) -> httpx.Response:
    data = json.loads((DATA / name).read_text(encoding='utf-8'))
    return httpx.Response(data['status'], json=data['body'])


class FakeLedger(UsageLedger):
    """本月費用固定的 UsageLedger（不連資料庫）。"""

    def __init__(self, pricing: Pricing, month: Decimal) -> None:
        super().__init__(cast(Database, None), pricing, job_budget=1, monthly_budget=20)
        self.month = month

    async def month_total(self) -> Decimal:
        return self.month


PRICING = Pricing.load(REPO_ROOT / 'pricing.yaml')


class Status:
    def __init__(self) -> None:
        self.clients: list[GeminiClient] = []

    async def __call__(
        self, settings: Settings, *, ledger: UsageLedger | None = None, key: str | None = KEY
    ) -> ComponentStatus:
        configured = (
            settings.model_copy(update={'gemini_api_key': SecretStr(key or '')}) if key is not None else settings
        )
        book = ledger or FakeLedger(PRICING, Decimal('1.23'))
        client = GeminiClient(configured, book)
        self.clients.append(client)
        services = cast(ApiServices, SimpleNamespace(settings=configured, gemini=client, ledger=book))
        return await _probe('gemini', LABEL, _gemini(services))


@pytest.fixture
async def status() -> AsyncIterator[Status]:
    s = Status()
    yield s
    for c in s.clients:
        await c.aclose()


def gemini_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, agent_mode='gemini', **overrides)


async def test_simulated_mode(status: Status) -> None:
    result = await status(Settings(_env_file=None, agent_mode='sim'))
    assert (result.status, result.detail) == ('sim', 'AGENT_MODE=sim：模擬 Agent 與 VLM 審查')


async def test_a_missing_key_is_an_error_with_a_hint(status: Status) -> None:
    result = await status(gemini_settings(), key='')
    assert (result.status, result.detail) == ('error', NOT_CONFIGURED)


async def test_pricing_problems_are_errors(status: Status) -> None:
    broken = FakeLedger(Pricing({}, problem='找不到單價表：/app/pricing.yaml'), Decimal(0))
    result = await status(gemini_settings(), ledger=broken)
    assert (result.status, result.detail) == ('error', '找不到單價表：/app/pricing.yaml')
    result = await status(gemini_settings(gemini_llm_model='gemini-x'))
    assert result.status == 'error'
    assert result.detail.startswith('pricing.yaml 沒有 gemini-x 的單價')


async def test_rejected_keys_and_unknown_models_are_errors(status: Status) -> None:
    with respx.mock() as mock:
        mock.get(url__regex=MODELS + 'gemini-3\\.8-flash$').mock(return_value=recorded('error-400-key.json'))
        result = await status(gemini_settings())
    assert (result.status, result.detail) == ('error', 'Gemini API key 無效或沒有權限')
    pricing = Pricing({'gemini-x': [Price(from_=date(2026, 1, 1), input=1, output=1)]})
    with respx.mock() as mock:
        mock.get(url__regex=MODELS + 'gemini-x$').mock(return_value=recorded('error-404.json'))
        result = await status(
            gemini_settings(gemini_llm_model='gemini-x', gemini_vlm_model='gemini-x'),
            ledger=FakeLedger(pricing, Decimal(0)),
        )
    assert (result.status, result.detail) == ('error', '找不到 Gemini 模型：gemini-x')


async def test_shows_the_models_the_month_cost_and_the_key_hint(status: Status) -> None:
    with respx.mock() as mock:
        route = mock.get(url__regex=MODELS + 'gemini-3\\.8-flash$').mock(return_value=recorded('model.json'))
        result = await status(gemini_settings())
    assert (result.status, result.detail) == ('ok', 'LLM／VLM gemini-3.8-flash・本月 US$1.23／上限 US$20・key …a1B2')
    assert KEY not in result.detail
    assert route.call_count == 1


async def test_check_model_is_cached_and_lists_both_models(status: Status) -> None:
    pricing = Pricing(
        {
            'gemini-3.8-flash': [Price(from_=date(2026, 1, 1), input=0.75, output=3.75)],
            'gemini-3.8-pro': [Price(from_=date(2026, 1, 1), input=2, output=12)],
        }
    )
    settings = gemini_settings(gemini_vlm_model='gemini-3.8-pro', gemini_monthly_budget_usd=0)
    book = FakeLedger(pricing, Decimal('0'))
    client = GeminiClient(settings.model_copy(update={'gemini_api_key': SecretStr(KEY)}), book)
    status.clients.append(client)
    services = cast(ApiServices, SimpleNamespace(settings=client.settings, gemini=client, ledger=book))
    with respx.mock() as mock:
        flash = mock.get(url__regex=MODELS + 'gemini-3\\.8-flash$').mock(return_value=recorded('model.json'))
        pro = mock.get(url__regex=MODELS + 'gemini-3\\.8-pro$').mock(return_value=recorded('model.json'))
        first = await _probe('gemini', LABEL, _gemini(services))
        await _probe('gemini', LABEL, _gemini(services))
    assert first.detail == 'LLM gemini-3.8-flash／VLM gemini-3.8-pro・本月 US$0.00／不設上限・key …a1B2'
    assert (flash.call_count, pro.call_count) == (1, 1)


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[ComposerClient]:
    client = ComposerClient(composer_url)
    yield client
    await client.aclose()


async def test_brand_files_with_glyphs_the_fonts_lack_get_a_warning(composer: ComposerClient) -> None:
    brands = [b.brand for b in load_brands(BRANDS_DIR)[0]]
    assert await glyph_warnings(composer, brands) == ''
    selune = next(b for b in brands if b.id == 'selune')
    presets = dict(selune.copy_presets)
    presets['gentle'] = presets['gentle'].model_copy(update={'subhead': '这样修護'})
    broken = selune.model_copy(
        update={'copy_presets': presets, 'replacements': {**selune.replacements, '根治': '改善们'}}
    )
    warning = await glyph_warnings(composer, [broken, *[b for b in brands if b.id != 'selune']])
    assert warning == f'；{selune.name} 的預設文案或替代用語有伺服器字型沒有的字：「这们」'
    unreachable = ComposerClient('http://127.0.0.1:9')
    try:
        assert await glyph_warnings(unreachable, [broken]) == ''
    finally:
        await unreachable.aclose()
