"""測試用的 ComfyUI：HTTP 以 respx 回應（tests/data/comfy/ 的 JSON），WebSocket 以 127.0.0.1 隨機埠的
websockets 伺服器依序送出錄製的訊息。不需要 GPU 與 ComfyUI。"""

import io
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import respx
from PIL import Image
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve

DATA = Path(__file__).parent / 'data' / 'comfy'
BASE = 'http://comfy.test'
PROMPT_ID = 'p-0001'


def data(name: str) -> Any:
    """tests/data/comfy/ 的 JSON（每次回傳新的物件）。"""
    return json.loads((DATA / name).read_text(encoding='utf-8'))


def png(size: tuple[int, int] = (64, 48), color: tuple[int, int, int] = (200, 120, 130)) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


def messages(name: str, prompt_id: str = PROMPT_ID) -> list[dict[str, Any]]:
    """錄製的 WebSocket 訊息，錄製時的 prompt_id（PROMPT_ID）換成這次測試的；其他 prompt 的訊息不變。"""
    out: list[dict[str, Any]] = data(name)
    for m in out:
        if m.get('data', {}).get('prompt_id') == PROMPT_ID:
            m['data']['prompt_id'] = prompt_id
    return out


class FakeWebSocket:
    """連上後依序送出 script（dict 送 JSON 文字，bytes 送二進位的預覽圖）；送完後 close 為 True 時關閉連線，
    否則保持連線直到測試結束（等待逾時或取消）。"""

    def __init__(self, script: Sequence[dict[str, Any] | bytes], close: bool = False) -> None:
        self.script = script
        self.close = close
        self.paths: list[str] = []
        self.port = 0

    async def _handle(self, ws: ServerConnection) -> None:
        self.paths.append(ws.request.path if ws.request else '')
        for item in self.script:
            await ws.send(item if isinstance(item, bytes) else json.dumps(item))
        if self.close:
            await ws.close()
            return
        await ws.wait_closed()  # 保持連線，直到用戶端關閉（伺服器關閉時也會結束）

    @asynccontextmanager
    async def serving(self) -> AsyncIterator['FakeWebSocket']:
        async with serve(self._handle, '127.0.0.1', 0) as server:
            self.port = next(iter(server.sockets)).getsockname()[1]
            yield self

    def connect(self, url: str) -> connect:
        """ComfyClient 的 connect_ws：忽略 comfyui_url 的主機，連到這個伺服器（保留路徑與 clientId）。"""
        path = url.split('/ws', 1)[1]
        return connect(f'ws://127.0.0.1:{self.port}/ws{path}')


def mock_http(
    router: respx.MockRouter,
    *,
    history: list[dict[str, Any]] | None = None,
    prompt_status: int = 200,
    prompt_body: dict[str, Any] | None = None,
    image: bytes | None = None,
) -> dict[str, respx.Route]:
    """ComfyUI 的 HTTP 端點；history 依序回傳（輪詢時先回空的 {} 再回完成的結果）。"""
    done = data('history.json')
    routes = {
        'system_stats': router.get(f'{BASE}/system_stats').respond(json=data('system_stats.json')),
        'object_info': router.get(f'{BASE}/object_info').respond(json=data('object_info.json')),
        'upload': router.post(f'{BASE}/upload/image').respond(
            json={'name': 'job_t_r1_ig-post_plate.png', 'subfolder': '', 'type': 'input'}
        ),
        'prompt': router.post(f'{BASE}/prompt').respond(
            prompt_status, json=prompt_body or {'prompt_id': PROMPT_ID, 'number': 1, 'node_errors': {}}
        ),
        'history': router.get(f'{BASE}/history/{PROMPT_ID}').mock(
            side_effect=[respx.MockResponse(json=h) for h in (history or [done])]
        ),
        'view': router.get(f'{BASE}/view').respond(content=image or png(), headers={'Content-Type': 'image/png'}),
        'interrupt': router.post(f'{BASE}/interrupt').respond(200),
        'queue': router.post(f'{BASE}/queue').respond(200),
        'free': router.post(f'{BASE}/free').respond(200),
    }
    return routes
