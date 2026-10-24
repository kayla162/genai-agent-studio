"""ComfyUI 的用戶端（IMAGE_MODE=comfyui，Plan 7 規格 §4.5）：HTTP（httpx）與 WebSocket（websockets）。

- system_stats：版本與 GPU（系統狀態、每輪生圖前檢查連線）
- missing：以 /object_info 檢查 workflow 用到的節點與模型（結果快取 60 秒）
- upload：上傳商品底圖與遮罩
- run：先連上 WebSocket 再送出 prompt，依 progress 回報進度；WebSocket 斷線時改以 /history 輪詢；
  完成後從 /history 找到輸出圖並以 /view 下載。等待經過 run.wait，取消或逾時時中斷正在執行的 prompt
  並從佇列刪除。這裡不重試，執行錯誤的重試在 ComfyImageEngine。
- free：請 ComfyUI 釋放模型與記憶體

錯誤訊息一律為中文，包含節點類型與 ComfyUI 的原始訊息。
"""

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from app.errors import AppError
from app.pipeline.ports import JobCancelled, RunContext
from app.settings import Settings

#: /object_info 的快取秒數
OBJECT_INFO_TTL = 60
#: HTTP 請求的逾時（秒）；等待 prompt 完成另以 comfyui_timeout_seconds 計算
HTTP_TIMEOUT = 30
#: GPU 記憶體不足時的建議
OOM_HINT = '請關閉其他使用 GPU 的程式，或以 --lowvram 啟動 ComfyUI'

ConnectWs = Callable[[str], AbstractAsyncContextManager[ClientConnection]]
OnProgress = Callable[[str, int, int], Awaitable[None]]


class ComfyError(AppError):
    """ComfyUI 連不上、拒絕 workflow、缺少節點或模型、逾時：重試也不會好。"""


class ComfyExecutionError(ComfyError):
    """prompt 執行時失敗（execution_error）：ComfyImageEngine 重試一次。"""

    def __init__(self, message: str, *, out_of_memory: bool = False) -> None:
        super().__init__(message)
        self.out_of_memory = out_of_memory


@dataclass(frozen=True)
class ComfyStats:
    version: str
    #: GPU 名稱（去掉 cuda:0 與記憶體配置器的說明）
    gpu: str
    #: VRAM 總量（位元組）
    vram_total: int


@dataclass(frozen=True)
class ComfyOutput:
    png: bytes
    #: 從開始執行到完成的秒數（不含排隊）
    seconds: float


def _gpu_name(device: dict[str, Any]) -> str:
    """'cuda:0 NVIDIA GeForce RTX 3060 Laptop GPU : cudaMallocAsync' → 'NVIDIA GeForce RTX 3060 Laptop GPU'"""
    name = str(device.get('name', ''))
    name = name.split(' : ', 1)[0]
    head, _, rest = name.partition(' ')
    return rest if ':' in head and rest else name


def _execution_error(data: dict[str, Any]) -> ComfyExecutionError:
    node = f'{data.get("node_type", "?")}（節點 {data.get("node_id", "?")}）'
    message = str(data.get('exception_message', '')).strip()
    kind = str(data.get('exception_type', ''))
    if 'OutOfMemoryError' in kind or 'out of memory' in message.lower():
        return ComfyExecutionError(f'ComfyUI 執行失敗：{node}GPU 記憶體不足。{OOM_HINT}', out_of_memory=True)
    return ComfyExecutionError(f'ComfyUI 執行失敗：{node}{kind.rsplit(".", 1)[-1]}：{message}')


def _rejected(body: Any) -> ComfyError:
    """POST /prompt 回 400：workflow 驗證失敗（例如找不到模型）。"""
    reasons: list[str] = []
    for node_id, node in (body.get('node_errors') or {}).items():
        for err in node.get('errors', []):
            reasons.append(
                f'{node.get("class_type", "?")}（節點 {node_id}）{err.get("message", "")}：{err.get("details", "")}'
            )
    if not reasons:
        error = body.get('error') or {}
        reasons.append(str(error.get('message') or error or body))
    return ComfyError(f'ComfyUI 拒絕這個 workflow：{"；".join(reasons)}')


def _first_image(history: dict[str, Any]) -> dict[str, Any] | None:
    for output in history.get('outputs', {}).values():
        for image in output.get('images', []):
            if image.get('type', 'output') == 'output':
                return dict(image)
    return None


class ComfyClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        connect_ws: ConnectWs | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.settings = settings
        self.base = settings.comfyui_url.rstrip('/')
        self._http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        self._connect_ws: ConnectWs = connect_ws or (lambda url: connect(url, max_size=None))
        self.poll_interval = poll_interval
        self._object_info: tuple[float, dict[str, Any]] | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, f'{self.base}{path}', **kwargs)
        except httpx.HTTPError as error:
            raise ComfyError(f'ComfyUI 沒有回應（{self.base}），請先啟動 ComfyUI') from error

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        res = await self._request(method, path, **kwargs)
        if res.status_code != 200:
            raise ComfyError(f'ComfyUI {path} 回應 HTTP {res.status_code}：{res.text[:200]}')
        return res.json()

    async def system_stats(self) -> ComfyStats:
        data = await self._json('GET', '/system_stats')
        device = (data.get('devices') or [{}])[0]
        return ComfyStats(
            version=str(data.get('system', {}).get('comfyui_version', '')),
            gpu=_gpu_name(device),
            vram_total=int(device.get('vram_total', 0)),
        )

    async def object_info(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._object_info is None or now - self._object_info[0] > OBJECT_INFO_TTL:
            self._object_info = (now, await self._json('GET', '/object_info'))
        return self._object_info[1]

    async def missing(self, workflow: dict[str, Any], ignore: Collection[tuple[str, str]] = ()) -> list[str]:
        """workflow 用到、但 ComfyUI 沒有的節點類型，以及不在選項清單裡的值（模型檔名、取樣器…）。
        ignore 為不檢查的 (nodeId, input)，例如每個任務上傳的底圖與遮罩。"""
        info = await self.object_info()
        problems: list[str] = []
        for node_id, node in workflow.items():
            kind = node['class_type']
            spec = info.get(kind)
            if spec is None:
                problems.append(f'缺少節點 {kind}')
                continue
            inputs = {**spec.get('input', {}).get('required', {}), **spec.get('input', {}).get('optional', {})}
            for name, value in node['inputs'].items():
                options = inputs.get(name, [None])[0]
                if (node_id, name) in ignore or not isinstance(options, list) or isinstance(value, list):
                    continue
                if value not in options:
                    problems.append(f'找不到 {kind} 的 {name}：{value}')
        return problems

    async def upload(self, name: str, png: bytes) -> str:
        data = await self._json(
            'POST',
            '/upload/image',
            files={'image': (name, png, 'image/png')},
            data={'overwrite': 'true', 'type': 'input'},
        )
        return str(data['name'])

    async def free(self) -> None:
        """請 ComfyUI 卸載模型並釋放記憶體（回應沒有內容）。"""
        res = await self._request('POST', '/free', json={'unload_models': True, 'free_memory': True})
        if res.status_code != 200:
            raise ComfyError(f'ComfyUI /free 回應 HTTP {res.status_code}')

    async def run(self, workflow: dict[str, Any], run: RunContext, on_progress: OnProgress) -> ComfyOutput:
        client_id = uuid.uuid4().hex
        ws_url = f'{self.base.replace("http", "ws", 1)}/ws?clientId={client_id}'
        async with self._connect_ws(ws_url) as ws:
            res = await self._request('POST', '/prompt', json={'prompt': workflow, 'client_id': client_id})
            if res.status_code == 400:
                raise _rejected(res.json())
            if res.status_code != 200:
                raise ComfyError(f'ComfyUI /prompt 回應 HTTP {res.status_code}：{res.text[:200]}')
            prompt_id = str(res.json()['prompt_id'])
            timeout = self.settings.comfyui_timeout_seconds
            try:
                history, seconds = await run.wait(
                    asyncio.wait_for(self._follow(ws, prompt_id, on_progress), timeout),
                    note='任務已取消：中斷 ComfyUI 正在執行的 prompt',
                )
            except JobCancelled:
                await self._drop(prompt_id)
                raise
            except TimeoutError as error:
                await self._drop(prompt_id)
                raise ComfyError(f'ComfyUI 沒有在 {timeout:g} 秒內完成（prompt {prompt_id}）') from error
        image = _first_image(history)
        if image is None:
            raise ComfyError(f'ComfyUI 完成了 prompt {prompt_id}，但沒有輸出圖片')
        res = await self._request(
            'GET',
            '/view',
            params={'filename': image['filename'], 'subfolder': image.get('subfolder', ''), 'type': 'output'},
        )
        if res.status_code != 200:
            raise ComfyError(f'無法下載 ComfyUI 的輸出圖（HTTP {res.status_code}）')
        return ComfyOutput(png=res.content, seconds=seconds)

    async def _follow(
        self, ws: ClientConnection, prompt_id: str, on_progress: OnProgress
    ) -> tuple[dict[str, Any], float]:
        """等這個 prompt 完成：回傳它的 /history 與執行秒數。"""
        started = time.monotonic()
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue  # 預覽圖
                message = json.loads(raw)
                data = message.get('data') or {}
                if data.get('prompt_id') != prompt_id:
                    continue
                kind = message.get('type')
                if kind == 'execution_start':
                    started = time.monotonic()
                elif kind == 'progress':
                    await on_progress(str(data.get('node')), int(data['value']), int(data['max']))
                elif kind == 'execution_error':
                    raise _execution_error(data)
                elif kind == 'execution_interrupted':
                    raise ComfyExecutionError(f'ComfyUI 中斷了 prompt {prompt_id}（節點 {data.get("node_type", "?")}）')
                elif kind == 'execution_success':
                    return await self._history(prompt_id), time.monotonic() - started
        except WebSocketException:
            pass  # 斷線：改以 /history 輪詢
        while True:
            history = await self._history(prompt_id)
            if history.get('status', {}).get('completed'):
                return history, time.monotonic() - started
            if history.get('status', {}).get('status_str') == 'error':
                errors = [m[1] for m in history['status'].get('messages', []) if m[0] == 'execution_error']
                raise _execution_error(errors[0] if errors else {})
            await asyncio.sleep(self.poll_interval)

    async def _history(self, prompt_id: str) -> dict[str, Any]:
        data = await self._json('GET', f'/history/{prompt_id}')
        return dict(data.get(prompt_id) or {})

    async def _drop(self, prompt_id: str) -> None:
        """中斷正在執行的 prompt，並從佇列刪除（還在排隊時）；ComfyUI 已經關閉時略過。"""
        for path, body in (('/interrupt', {'prompt_id': prompt_id}), ('/queue', {'delete': [prompt_id]})):
            with contextlib.suppress(ComfyError):
                await self._request('POST', path, json=body)
