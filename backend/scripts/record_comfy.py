"""錄製 ComfyUI 的回應給測試重播（tests/data/comfy/）：以示範品牌 selune 的 IG 貼文跑一次真的 workflow。

用法（在 backend/，需要啟動中的 ComfyUI 與 composer：在 web/ 執行 npm run composer）：

    uv run python -m scripts.record_comfy [--comfyui http://127.0.0.1:8188] [--composer http://127.0.0.1:3900]

- 寫入 system_stats.json、object_info.json（只保留 workflow 用到的節點類型）、history.json 與 ws-success.json
  （WebSocket 的文字訊息；預覽圖等二進位訊息不錄）。prompt_id 一律換成 p-0001，與 tests/fake_comfy.py 相同。
- 錯誤的情況（ws-error.json、ws-oom.json、ws-progress-only.json、prompt-invalid.json）維持手寫，不會被覆寫。
- 生成的背景存在 data/jobs/job_record/bg-ig-post-r1-v0.png（data/ 不進 git），可以打開檢查。
"""

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
from websockets.asyncio.client import ClientConnection, connect

from app.adapters.comfyui import ComfyClient
from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import JobEvent, LogLevel, LogSource, Render
from app.pipeline.comfy import ComfyImageEngine, load_workflow
from app.settings import REPO_ROOT, Settings

DATA = Path(__file__).resolve().parents[1] / 'tests' / 'data' / 'comfy'
TIMELINE = REPO_ROOT / 'contracts' / 'fixtures' / 'timelines' / 'selune-retry.json'
#: 錄製後的 prompt_id（tests/fake_comfy.py 的 PROMPT_ID）
RECORDED_ID = 'p-0001'


class PrintRun:
    job_id = 'job_record'

    async def emit(self, event: JobEvent) -> None:
        return None

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        print(f'[{source}] {message}')

    async def pace(self, ms: float) -> None:
        return None

    async def wait(self, awaitable: Any, note: str | None = None) -> Any:
        return await awaitable


class Recorder:
    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.messages: list[dict[str, Any]] = []

    async def on_response(self, res: httpx.Response) -> None:
        path = res.request.url.path
        if res.request.method == 'GET' and (path in ('/system_stats', '/object_info') or path.startswith('/history/')):
            await res.aread()
            self.responses[path.split('/')[1]] = res.json()

    @asynccontextmanager
    async def connect(self, url: str) -> AsyncIterator[ClientConnection]:
        async with connect(url, max_size=None) as ws:
            recorder = self

            class Recording:
                def __aiter__(self) -> AsyncIterator[str | bytes]:
                    return self._messages()

                async def _messages(self) -> AsyncIterator[str | bytes]:
                    async for raw in ws:
                        if isinstance(raw, str):
                            recorder.messages.append(json.loads(raw))
                        yield raw

            yield cast(ClientConnection, Recording())


def rename(value: Any, prompt_id: str) -> Any:
    """把真的 prompt_id 換成 RECORDED_ID（字典的鍵與值都換）。"""
    text = json.dumps(value, ensure_ascii=False).replace(prompt_id, RECORDED_ID)
    return json.loads(text)


def write(name: str, value: Any) -> None:
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'寫入 {DATA / name}')


async def main(args: argparse.Namespace) -> None:
    settings = Settings(_env_file=None, image_mode='comfyui', agent_mode='sim', comfyui_url=args.comfyui)
    timeline = json.loads(TIMELINE.read_text(encoding='utf-8'))
    render = next(
        Render.model_validate(r)
        for item in timeline['events']
        if item['event']['type'] == 'render.completed' and item['event']['round'] == 2
        for r in item['event']['renders']
        if r['templateId'] == 'ig-post' and r['variant'] == 0
    )
    loaded = {b.brand.id: b for b in load_brands(REPO_ROOT / 'brands')[0]}['selune']
    product = next(p for p in loaded.samples if p.id == 'prod_selune_serum')
    recorder = Recorder()
    composer = ComposerClient(args.composer)
    async with httpx.AsyncClient(timeout=30, event_hooks={'response': [recorder.on_response]}) as http:
        comfy = ComfyClient(settings, http, connect_ws=recorder.connect)
        engine = ComfyImageEngine(comfy, composer, settings)
        out = await engine.render_round('job_record', 1, [render.spec], 1, loaded.brand, product, PrintRun())
    await composer.aclose()
    print(out)

    prompt_id = next(m['data']['prompt_id'] for m in recorder.messages if 'prompt_id' in m.get('data', {}))
    workflow, _ = load_workflow(settings.comfyui_workflows_dir)
    used = {n['class_type'] for n in workflow.values()}
    write('system_stats.json', recorder.responses['system_stats'])
    write('object_info.json', {k: v for k, v in recorder.responses['object_info'].items() if k in used})
    write('history.json', rename(recorder.responses['history'], prompt_id))
    write('ws-success.json', [rename(m, prompt_id) for m in recorder.messages])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--comfyui', default='http://127.0.0.1:8188')
    parser.add_argument('--composer', default='http://127.0.0.1:3900')
    asyncio.run(main(parser.parse_args()))
