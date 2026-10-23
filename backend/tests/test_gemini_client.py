"""GeminiClient：以 respx 重播 Gemini 的 REST 回應（tests/data/gemini/），不呼叫真 API、不需要資料庫。

涵蓋結構化輸出、用量（含快取與思考）、重試、格式錯誤時重問、安全性過濾、中文的錯誤原因、逾時、取消、上限，
以及 key 不會出現在任何錯誤訊息與 log。
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.adapters.gemini import (
    INTERRUPTED_NOTE,
    NOT_CONFIGURED,
    GeminiCall,
    GeminiClient,
    GeminiError,
    gemini_schema,
    usage_message,
)
from app.errors import BudgetExceeded
from app.pipeline.ports import JobCancelled
from app.settings import Settings
from app.usage import TokenUsage, UsageKind, UsageScope
from tests.fake_run import FakeRun

DATA = Path(__file__).parent / 'data' / 'gemini'
KEY = 'AIza-test-key-0000'
GENERATE = r'https://generativelanguage\.googleapis\.com/v1beta/models/[^/:]+:generateContent'
MODEL_URL = r'https://generativelanguage\.googleapis\.com/v1beta/models/[^/:]+$'
SCOPE = UsageScope(job_id='job_g', brand_id='selune', round=1, target='ig-post')


class Headline(BaseModel):
    """測試用的小模型（對應 ok.json 與 invalid.json）。"""

    headline: str
    points: list[str]


def recorded(name: str) -> httpx.Response:
    data = json.loads((DATA / name).read_text(encoding='utf-8'))
    return httpx.Response(data['status'], json=data['body'])


class MemoryUsage:
    """記憶體版的 UsageRecorder：每百萬 tokens 輸入 0.75、輸出 3.75（不計快取折扣）。"""

    def __init__(self, exceeded: str | None = None) -> None:
        self.records: list[tuple[UsageScope, UsageKind, str, TokenUsage]] = []
        self.checks = 0
        self.exceeded = exceeded

    async def check(self, scope: UsageScope, model: str) -> None:
        self.checks += 1
        if self.exceeded:
            raise BudgetExceeded(self.exceeded)

    async def record(self, scope: UsageScope, kind: UsageKind, model: str, usage: TokenUsage) -> Decimal:
        self.records.append((scope, kind, model, usage))
        return (
            Decimal(usage.input_tokens) * Decimal('0.75') + Decimal(usage.output_tokens) * Decimal('3.75')
        ) / 1_000_000


class Harness:
    def __init__(self, client: GeminiClient, usage: MemoryUsage, sleeps: list[float]) -> None:
        self.client = client
        self.usage = usage
        self.sleeps = sleeps
        self.run = FakeRun('job_g')

    def call(self, kind: UsageKind = 'spec') -> GeminiCall[Headline]:
        return GeminiCall(
            kind=kind,
            model='gemini-3.8-flash',
            system='你是海報文案助理',
            parts=['寫一個標題'],
            schema=Headline,
            scope=SCOPE,
            seed=42,
        )

    def everything_said(self) -> str:
        return '\n'.join(self.run.messages())


MakeHarness = Callable[..., Harness]


@pytest.fixture
async def make() -> AsyncIterator[MakeHarness]:
    http = httpx.AsyncClient()
    created: list[GeminiClient] = []

    def build(key: str = KEY, usage: MemoryUsage | None = None, **overrides: Any) -> Harness:
        settings = Settings(_env_file=None, agent_mode='gemini', gemini_api_key=key, **overrides)
        sleeps: list[float] = []

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        recorder = usage or MemoryUsage()
        client = GeminiClient(settings, recorder, http=http, sleep=sleep, jitter=0)
        created.append(client)
        return Harness(client, recorder, sleeps)

    yield build
    for c in created:
        await c.aclose()
    await http.aclose()


async def test_parses_structured_output_and_records_usage(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        route = mock.post(url__regex=GENERATE).mock(return_value=recorded('ok.json'))
        result = await h.client.generate(h.call(), h.run)
    assert result == Headline(headline='醒來透亮發光', points=['5重玻尿酸', '神經醯胺'])
    body = json.loads(route.calls[0].request.content)
    assert body['contents'] == [{'parts': [{'text': '寫一個標題'}], 'role': 'user'}]
    assert body['systemInstruction']['parts'] == [{'text': '你是海報文案助理'}]
    config = body['generationConfig']
    assert (config['responseMimeType'], config['seed']) == ('application/json', 42)
    assert config['responseJsonSchema'] == gemini_schema(Headline)
    assert config['thinkingConfig'] == {'thinking_level': 'HIGH'}
    assert route.calls[0].request.headers['x-goog-api-key'] == KEY
    usage = TokenUsage(input_tokens=4120, cached_tokens=1000, output_tokens=392 + 640, thinking_tokens=640)
    assert h.usage.records == [(SCOPE, 'spec', 'gemini-3.8-flash', usage)]
    assert h.run.logs == [('agent', 'info', usage_message('gemini-3.8-flash', usage, Decimal('0.006960')))]
    assert usage_message('gemini-3.8-flash', usage, Decimal('0.006960')) == (
        'gemini-3.8-flash：輸入 4,120（快取 1,000）／輸出 1,032（思考 640）tokens・US$0.0070'
    )


async def test_vlm_calls_log_to_the_vlm_source(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        mock.post(url__regex=GENERATE).mock(return_value=recorded('ok.json'))
        await h.client.generate(h.call('vlm'), h.run)
    assert [source for source, _, _ in h.run.logs] == ['vlm']


async def test_retries_429_with_the_suggested_delay(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        route = mock.post(url__regex=GENERATE).mock(side_effect=[recorded('error-429.json'), recorded('ok.json')])
        await h.client.generate(h.call(), h.run)
    assert route.call_count == 2
    assert h.sleeps == [2.0]
    assert len(h.usage.records) == 1
    assert any('2.0 秒後重試（1/3）' in m for m in h.run.messages('warn'))


async def test_gives_up_on_5xx_after_the_retries(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        route = mock.post(url__regex=GENERATE).mock(return_value=recorded('error-503.json'))
        with pytest.raises(GeminiError, match=r'^Gemini 暫時無法使用（HTTP 503），已重試 3 次$'):
            await h.client.generate(h.call(), h.run)
    assert route.call_count == 4
    assert h.sleeps == [1.0, 2.0, 4.0]
    assert h.usage.records == []


async def test_asks_again_with_the_format_error(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        route = mock.post(url__regex=GENERATE).mock(side_effect=[recorded('invalid.json'), recorded('ok.json')])
        result = await h.client.generate(h.call(), h.run)
    assert result.points == ['5重玻尿酸', '神經醯胺']
    second = json.loads(route.calls[1].request.content)['contents']
    assert [c['role'] for c in second] == ['user', 'model', 'user']
    assert second[1]['parts'][0]['text'].startswith('{"headline"')
    assert second[2]['parts'][0]['text'] == '上一次的回應格式錯誤：points：必須是陣列。請修正後重新輸出完整的 JSON。'
    assert len(h.usage.records) == 2
    assert h.usage.checks == 2


async def test_fails_when_the_format_is_still_wrong(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        mock.post(url__regex=GENERATE).mock(return_value=recorded('invalid.json'))
        with pytest.raises(GeminiError, match=r'^Gemini 回應格式錯誤（Prompt 構建）：points：必須是陣列$'):
            await h.client.generate(h.call(), h.run)
    assert len(h.usage.records) == 2


@pytest.mark.parametrize(
    ('response', 'reason'),
    [
        ('blocked.json', 'Gemini 拒絕產生內容（安全性過濾）'),
        ('error-400-key.json', 'Gemini API key 無效或沒有權限'),
        ('error-403.json', 'Gemini API key 無效或沒有權限'),
        ('error-404.json', '找不到 Gemini 模型：gemini-3.8-flash'),
    ],
)
async def test_does_not_retry_errors_that_will_not_go_away(make: MakeHarness, response: str, reason: str) -> None:
    h = make()
    with respx.mock() as mock:
        route = mock.post(url__regex=GENERATE).mock(return_value=recorded(response))
        with pytest.raises(GeminiError) as caught:
            await h.client.generate(h.call(), h.run)
    assert caught.value.message == reason
    assert route.call_count == 1
    # 安全性過濾的回應仍有用量；錯誤回應沒有
    assert len(h.usage.records) == (1 if response == 'blocked.json' else 0)


async def test_bad_requests_keep_the_gemini_message(make: MakeHarness) -> None:
    h = make()
    body = {'error': {'code': 400, 'message': 'Invalid JSON payload received.', 'status': 'INVALID_ARGUMENT'}}
    with respx.mock() as mock:
        mock.post(url__regex=GENERATE).mock(return_value=httpx.Response(400, json=body))
        with pytest.raises(GeminiError, match=r'^Gemini 請求錯誤：Invalid JSON payload received\.$'):
            await h.client.generate(h.call(), h.run)


async def test_times_out_and_retries(make: MakeHarness) -> None:
    h = make(gemini_timeout_seconds=0.05, gemini_max_retries=1)
    requests: list[httpx.Request] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await asyncio.sleep(1)
        return recorded('ok.json')

    # 被中斷的請求不算 respx 的 call，所以自己計數
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=GENERATE).mock(side_effect=slow)
        with pytest.raises(GeminiError, match=r'^Gemini 沒有在 0\.05 秒內回應，已重試 1 次$'):
            await h.client.generate(h.call(), h.run)
    assert len(requests) == 2


async def test_cancelling_interrupts_the_request_without_recording_usage(make: MakeHarness) -> None:
    h = make()
    started = asyncio.Event()
    interrupted = asyncio.Event()

    async def hang(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return recorded('ok.json')

    async def cancel_soon() -> None:
        await started.wait()
        h.run.cancelled = True

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=GENERATE).mock(side_effect=hang)
        canceller = asyncio.create_task(cancel_soon())
        with pytest.raises(JobCancelled):
            await asyncio.wait_for(h.client.generate(h.call(), h.run), 2)
        await canceller
    assert interrupted.is_set()
    assert h.usage.records == []
    assert h.run.messages('warn') == [INTERRUPTED_NOTE]


async def test_does_not_call_gemini_over_budget_or_without_a_key(make: MakeHarness) -> None:
    h = make(usage=MemoryUsage(exceeded='本月 Gemini 費用已達上限（US$20.00）'))
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(url__regex=GENERATE).mock(return_value=recorded('ok.json'))
        with pytest.raises(BudgetExceeded, match='本月 Gemini 費用已達上限'):
            await h.client.generate(h.call(), h.run)
        nokey = make(key='')
        assert not nokey.client.configured
        with pytest.raises(GeminiError) as caught:
            await nokey.client.generate(nokey.call(), nokey.run)
    assert caught.value.message == NOT_CONFIGURED
    assert route.call_count == 0


async def test_the_key_never_appears_in_errors_or_logs(make: MakeHarness) -> None:
    h = make(gemini_max_retries=1)
    leaky = {'error': {'code': 500, 'message': f'internal error for key {KEY}', 'status': 'INTERNAL'}}
    bad = {'error': {'code': 400, 'message': f'bad request with {KEY}', 'status': 'INVALID_ARGUMENT'}}
    responses = [httpx.Response(500, json=leaky), httpx.Response(500, json=leaky), httpx.Response(400, json=bad)]
    with respx.mock() as mock:
        mock.post(url__regex=GENERATE).mock(side_effect=responses)
        with pytest.raises(GeminiError) as server:
            await h.client.generate(h.call(), h.run)
        with pytest.raises(GeminiError) as client:
            await h.client.generate(h.call(), h.run)
    for text in (server.value.message, str(server.value), client.value.message, h.everything_said()):
        assert KEY not in text
    assert '***' in client.value.message


async def test_check_model_uses_models_get_and_caches_the_result(make: MakeHarness) -> None:
    h = make()
    with respx.mock() as mock:
        ok = mock.get(url__regex=MODEL_URL.replace('[^/:]+', r'gemini-3\.8-flash')).mock(
            return_value=recorded('model.json')
        )
        missing = mock.get(url__regex=MODEL_URL.replace('[^/:]+', 'gemini-x')).mock(
            return_value=recorded('error-404.json')
        )
        await h.client.check_model('gemini-3.8-flash')
        await h.client.check_model('gemini-3.8-flash')
        assert ok.call_count == 1
        for _ in range(2):
            with pytest.raises(GeminiError, match='^找不到 Gemini 模型：gemini-x$'):
                await h.client.check_model('gemini-x')
        assert missing.call_count == 1


def test_gemini_schema_inlines_references_and_keeps_property_names() -> None:
    class Fix(BaseModel):
        title: str
        desc: str

    class Plan(BaseModel):
        fixes: list[Fix]
        note: str | None = None

    schema = gemini_schema(Plan)
    text = json.dumps(schema)
    assert '$ref' not in text and '$defs' not in text
    assert 'default' not in schema['properties']['note']
    assert set(schema['properties']['fixes']['items']['properties']) == {'title', 'desc'}
    assert 'title' not in schema
