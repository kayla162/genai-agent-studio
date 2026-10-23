"""Gemini（官方 google-genai SDK 的 client.aio）：結構化輸出、重試、逾時、取消、用量與費用上限。

每次呼叫（generate）：
1. 檢查費用上限（UsageRecorder.check）；超過時不送出。
2. 送出：JSON 輸出（response_json_schema 由 Pydantic 模型產生）、系統指示、思考程度（依呼叫種類）與任務的 seed。
   SDK 本身不重試；429、5xx、逾時與連線錯誤由這裡依指數退避重試，等待都經過 run.wait（可取消）。
3. 每個有回應的請求都寫入用量並送出 log；回應不符合格式時，帶著中文的錯誤說明重問一次。

key 只在建立 SDK client 時使用；所有錯誤訊息與 log 在輸出前把 key 換成 ***。
"""

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.contract import LogSource
from app.errors import AppError
from app.pipeline.ports import RunContext
from app.settings import Settings
from app.usage import TokenUsage, UsageKind, UsageRecorder, UsageScope
from app.validation import describe_errors

logger = logging.getLogger(__name__)

#: 呼叫種類的中文名稱（錯誤訊息用）
KIND_LABEL: dict[UsageKind, str] = {
    'brief': '需求拆解',
    'spec': 'Prompt 構建',
    'rewrite': 'Query Rewriting',
    'vlm': 'VLM 審查',
}
#: 每種呼叫的思考程度（實驗決定，見規格 §2、§12）
THINKING: dict[UsageKind, types.ThinkingLevel] = {
    'brief': types.ThinkingLevel.LOW,
    'spec': types.ThinkingLevel.HIGH,
    'rewrite': types.ThinkingLevel.LOW,
    'vlm': types.ThinkingLevel.LOW,
}
#: 429 建議的等待時間上限（秒）
MAX_RETRY_DELAY = 60.0
#: models.get 的結果（key 與模型是否可用）快取的秒數
MODEL_CHECK_TTL = 60.0
#: 回應因安全性停止的 finish_reason
BLOCKED_FINISH = {
    types.FinishReason.SAFETY,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.SPII,
    types.FinishReason.IMAGE_SAFETY,
}

NOT_CONFIGURED = '未設定 GEMINI_API_KEY：在 .env 加入後重新啟動 api 與 worker，或設 AGENT_MODE=sim'
INTERRUPTED_NOTE = '已中斷進行中的 Gemini 呼叫，這次呼叫可能仍會計費（未記錄用量）'
SAFETY_BLOCKED = 'Gemini 拒絕產生內容（安全性過濾）'
KEY_REJECTED = 'Gemini API key 無效或沒有權限'


class GeminiError(AppError):
    """Gemini 無法完成呼叫（重試後仍失敗、key 無效、找不到模型、格式錯誤、安全性過濾）。"""

    status = 503
    code = 'unavailable'


@dataclass(frozen=True)
class GeminiCall[T: BaseModel]:
    kind: UsageKind
    model: str
    #: 系統指示（prompts/*.md）
    system: str
    #: user 訊息：文字或圖片
    parts: Sequence[types.Part | str]
    #: 結構化輸出的 Pydantic 模型
    schema: type[T]
    scope: UsageScope
    #: 任務的 seed，盡量讓結果可以重現（不保證）
    seed: int | None = None


class LlmClient(Protocol):
    async def generate[T: BaseModel](self, call: GeminiCall[T], run: RunContext) -> T: ...


def gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic 模型的 JSON Schema（camelCase）：展開 $ref、去掉 title 與 default（properties 的欄位名稱不動）。"""
    schema = model.model_json_schema(by_alias=True)
    defs: dict[str, Any] = schema.pop('$defs', {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(x) for x in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            return resolve(defs[node['$ref'].rsplit('/', 1)[-1]])
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ('title', 'default'):
                continue
            out[key] = {k: resolve(v) for k, v in value.items()} if key == 'properties' else resolve(value)
        return out

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def token_usage(response: types.GenerateContentResponse) -> TokenUsage:
    """輸出 tokens 包含思考（計費方式相同），思考另外記錄。"""
    meta = response.usage_metadata
    if meta is None:
        return TokenUsage(0, 0, 0, 0)
    thinking = meta.thoughts_token_count or 0
    return TokenUsage(
        input_tokens=meta.prompt_token_count or 0,
        cached_tokens=meta.cached_content_token_count or 0,
        output_tokens=(meta.candidates_token_count or 0) + thinking,
        thinking_tokens=thinking,
    )


def usage_message(model: str, usage: TokenUsage, cost: Decimal) -> str:
    """gemini-3.8-flash：輸入 4,120（快取 0）／輸出 1,032（思考 640）tokens・US$0.0070"""
    return (
        f'{model}：輸入 {usage.input_tokens:,}（快取 {usage.cached_tokens:,}）'
        f'／輸出 {usage.output_tokens:,}（思考 {usage.thinking_tokens:,}）tokens・US${cost:.4f}'
    )


def _source(kind: UsageKind) -> LogSource:
    return 'vlm' if kind == 'vlm' else 'agent'


def _retry_delay(error: errors.APIError) -> float | None:
    """429 的 RetryInfo.retryDelay（例如 "20s"）；沒有時為 None。"""
    details = error.details.get('error', {}).get('details', []) if isinstance(error.details, dict) else []
    for item in details if isinstance(details, list) else []:
        if isinstance(item, dict) and str(item.get('@type', '')).endswith('RetryInfo'):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)s', str(item.get('retryDelay', '')))
            if match:
                return min(float(match.group(1)), MAX_RETRY_DELAY)
    return None


def _key_rejected(error: errors.APIError) -> bool:
    if error.code in (401, 403):
        return True
    text = f'{error.message} {error.details}'
    return error.code == 400 and ('API_KEY_INVALID' in text or 'API key not valid' in text)


class _Retryable(Exception):
    def __init__(self, reason: str, delay: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.delay = delay


class GeminiClient(LlmClient):
    def __init__(
        self,
        settings: Settings,
        usage: UsageRecorder,
        *,
        http: httpx.AsyncClient | None = None,
        backoff: Sequence[float] = (1.0, 2.0, 4.0),
        jitter: float = 0.2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.usage = usage
        self.backoff = tuple(backoff)
        self.jitter = jitter
        self._sleep = sleep
        self._key = settings.gemini_api_key.get_secret_value()
        self._semaphore = asyncio.Semaphore(settings.gemini_concurrency)
        self._model_checks: dict[str, tuple[float, str | None]] = {}
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        self._client = (
            genai.Client(
                api_key=self._key,
                http_options=types.HttpOptions(
                    httpx_async_client=self._http, retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
            if self._key
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    @property
    def key_hint(self) -> str:
        """系統狀態顯示的 key 末 4 碼"""
        return f'…{self._key[-4:]}' if self._key else ''

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    def redact(self, text: str) -> str:
        return text.replace(self._key, '***') if self._key else text

    def _error(self, message: str) -> GeminiError:
        return GeminiError(self.redact(message))

    async def generate[T: BaseModel](self, call: GeminiCall[T], run: RunContext) -> T:
        if self._client is None:
            raise GeminiError(NOT_CONFIGURED)
        parts = [types.Part.from_text(text=p) if isinstance(p, str) else p for p in call.parts]
        contents: list[types.Content] = [types.Content(role='user', parts=parts)]
        config = types.GenerateContentConfig(
            system_instruction=call.system,
            response_mime_type='application/json',
            response_json_schema=gemini_schema(call.schema),
            seed=call.seed,
            thinking_config=types.ThinkingConfig(thinking_level=THINKING[call.kind]),
        )
        for attempt in (1, 2):
            await self.usage.check(call.scope, call.model)
            response = await self._send(call, contents, config, run)
            usage = token_usage(response)
            cost = await self.usage.record(call.scope, call.kind, call.model, usage)
            await run.log(_source(call.kind), usage_message(call.model, usage, cost))
            self._raise_if_blocked(response)
            text = response.text or ''
            try:
                return call.schema.model_validate_json(text)
            except ValidationError as error:
                problem = self.redact(describe_errors(error.errors()))
            if attempt == 2:
                raise self._error(f'Gemini 回應格式錯誤（{KIND_LABEL[call.kind]}）：{problem}')
            await run.log(_source(call.kind), f'{call.model}：回應格式錯誤，帶著錯誤重問一次（{problem}）', 'warn')
            contents = [
                *contents,
                types.Content(role='model', parts=[types.Part.from_text(text=text)]),
                types.Content(
                    role='user',
                    parts=[
                        types.Part.from_text(text=f'上一次的回應格式錯誤：{problem}。請修正後重新輸出完整的 JSON。')
                    ],
                ),
            ]
        raise AssertionError('unreachable')

    def _raise_if_blocked(self, response: types.GenerateContentResponse) -> None:
        feedback = response.prompt_feedback
        finish = response.candidates[0].finish_reason if response.candidates else None
        if (feedback is not None and feedback.block_reason is not None) or finish in BLOCKED_FINISH:
            raise GeminiError(SAFETY_BLOCKED)

    async def _send[T: BaseModel](
        self,
        call: GeminiCall[T],
        contents: list[types.Content],
        config: types.GenerateContentConfig,
        run: RunContext,
    ) -> types.GenerateContentResponse:
        """送出一次請求；429、5xx、逾時與連線錯誤重試，其他錯誤直接丟出中文原因。"""
        assert self._client is not None
        retries = self.settings.gemini_max_retries
        for attempt in range(retries + 1):
            try:
                async with self._semaphore:
                    request = self._client.aio.models.generate_content(
                        model=call.model, contents=contents, config=config
                    )
                    return await run.wait(
                        asyncio.wait_for(request, self.settings.gemini_timeout_seconds), note=INTERRUPTED_NOTE
                    )
            except _Retryable as failure:
                retry = failure
            except errors.APIError as error:
                retry = self._classify(error, call.model)
            except (TimeoutError, httpx.TimeoutException):
                retry = _Retryable(f'Gemini 沒有在 {self.settings.gemini_timeout_seconds:g} 秒內回應')
            except httpx.TransportError as error:
                retry = _Retryable(f'連不上 Gemini（{type(error).__name__}）')
            if attempt == retries:
                raise self._error(f'{retry.reason}，已重試 {retries} 次')
            delay = retry.delay
            if delay is None:
                base = self.backoff[min(attempt, len(self.backoff) - 1)]
                delay = base * random.uniform(1 - self.jitter, 1 + self.jitter)
            await run.log(
                _source(call.kind),
                self.redact(f'{call.model}：{retry.reason}，{delay:.1f} 秒後重試（{attempt + 1}/{retries}）'),
                'warn',
            )
            await run.wait(self._sleep(delay))
        raise AssertionError('unreachable')

    def _classify(self, error: errors.APIError, model: str) -> _Retryable:
        """可以重試的錯誤回傳 _Retryable；其他丟出中文的 GeminiError。"""
        code = error.code
        if code == 429:
            return _Retryable('Gemini 請求太頻繁或超過配額（HTTP 429）', _retry_delay(error))
        if code == 408 or code >= 500:
            return _Retryable(f'Gemini 暫時無法使用（HTTP {code}）')
        if _key_rejected(error):
            raise self._error(KEY_REJECTED) from None
        if code == 404:
            raise self._error(f'找不到 Gemini 模型：{model}') from None
        if code == 400:
            raise self._error(f'Gemini 請求錯誤：{error.message or error.status}') from None
        raise self._error(f'Gemini 請求失敗（HTTP {code}）：{error.message or error.status}') from None

    async def check_model(self, model: str) -> None:
        """以 models.get 確認 key 與模型可用（不計費）；結果快取 MODEL_CHECK_TTL 秒。失敗時丟出 GeminiError。"""
        if self._client is None:
            raise GeminiError(NOT_CONFIGURED)
        cached = self._model_checks.get(model)
        now = time.monotonic()
        if cached is None or now - cached[0] > MODEL_CHECK_TTL:
            problem: str | None = None
            try:
                await asyncio.wait_for(self._client.aio.models.get(model=model), self.settings.gemini_timeout_seconds)
            except errors.APIError as error:
                try:
                    problem = self._classify(error, model).reason
                except GeminiError as rejected:
                    problem = rejected.message
            except (TimeoutError, httpx.HTTPError) as error:
                problem = f'連不上 Gemini（{type(error).__name__}）'
            cached = (now, problem)
            self._model_checks[model] = cached
        if cached[1] is not None:
            raise self._error(cached[1])
