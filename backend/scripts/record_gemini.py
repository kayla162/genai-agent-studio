"""錄製 Gemini 的回應給 respx 重播（tests/data/gemini/）：需求拆解、Prompt 構建與 VLM 審查各呼叫一次真的 API。

用法（在 backend/，需要 GEMINI_API_KEY 與執行中的 composer：在 web/ 執行 npm run composer）：

    uv run python scripts/record_gemini.py [--env-file ../.env] [--composer http://127.0.0.1:3900]

- key 取自環境變數 GEMINI_API_KEY，沒有時只讀 --env-file 的 GEMINI_API_KEY 這一個值。
- 寫入 brief-ok.json、spec-ok.json、vlm-ok.json：只有回應的狀態碼與本文（不含標頭），並確認不含 key。
- 錯誤回應（429、503、400、403、404）與安全性過濾的檔案維持手寫，不會被覆寫。
- 會產生費用（三次呼叫，約 US$0.01–0.03）。
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiClient
from app.brands import load_brands
from app.contract import JobEvent, LogLevel, LogSource, ProceduralBackground, RagHit, Render
from app.pipeline.gemini import GeminiAgent, GeminiReviewer
from app.pipeline.ports import SpecRequest
from app.pipeline.review import ComposerPosters
from app.settings import REPO_ROOT, Settings
from app.templates import get_template
from app.usage import MemoryLedger, Pricing

DATA = Path(__file__).resolve().parents[1] / 'tests' / 'data' / 'gemini'
TEXT = '週年慶 10/15–11/15 主打買一送一，要溫柔療癒的感覺'


def api_key(env_file: Path) -> str:
    key = os.environ.get('GEMINI_API_KEY') or (
        dotenv_values(env_file).get('GEMINI_API_KEY') if env_file.is_file() else None
    )
    if not key:
        sys.exit(f'沒有 GEMINI_API_KEY：請設定環境變數，或寫進 {env_file}')
    return key


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


async def main(env_file: Path, composer_url: str) -> None:
    key = api_key(env_file)
    responses: list[httpx.Response] = []

    async def keep(response: httpx.Response) -> None:
        if response.request.url.path.endswith(':generateContent'):
            await response.aread()
            responses.append(response)

    def save(name: str) -> None:
        last = responses[-1]
        text = json.dumps({'status': last.status_code, 'body': last.json()}, ensure_ascii=False, indent=2)
        if key in text:
            sys.exit(f'{name} 含有 key，沒有寫入')
        (DATA / name).write_text(text + '\n', encoding='utf-8')
        print(f'wrote tests/data/gemini/{name}')

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(_env_file=None, agent_mode='gemini', gemini_api_key=key, data_dir=Path(tmp) / 'data')
        ledger = MemoryLedger(Pricing.load(REPO_ROOT / 'pricing.yaml'))
        http = httpx.AsyncClient(event_hooks={'response': [keep]})
        client = GeminiClient(settings, ledger, http=http)
        composer = ComposerClient(composer_url)
        try:
            loaded = {b.brand.id: b for b in load_brands(REPO_ROOT / 'brands')[0]}['selune']
            brand, product = loaded.brand, loaded.samples[0]
            agent = GeminiAgent(client, composer, settings)
            run = PrintRun()

            brief = await agent.parse_brief(brand, TEXT, product)
            save('brief-ok.json')

            hits = [
                RagHit(chunk_id=c.id, source=c.source, section=c.section, tag=c.tag, text=c.text, vector_score=0.9)
                for c in brand.guideline_chunks
                if c.tag in ('color', 'law', 'layout')
            ]
            request = SpecRequest(
                'job_record', 1, brand, product, brief, get_template('ig-post'), 'comfyui', 123456789,
                [h.chunk_id for h in hits], [], text=TEXT, hits=hits,
            )  # fmt: skip
            spec = await agent.build_spec(request, run)
            save('spec-ok.json')

            render = Render(
                id='job_record_r1_ig-post_v0', job_id='job_record', round=1, template_id='ig-post', variant=0,
                background=ProceduralBackground(kind='procedural', seed=1, palette=spec.palette, style=brand.id),
                spec=spec, score=None, passed=None, checks=[],
            )  # fmt: skip
            poster = await ComposerPosters(composer, settings).compose('job_record', render, product, brand)
            await GeminiReviewer(client, composer, settings).review(brand, render, 7, poster, run)
            save('vlm-ok.json')
        finally:
            await composer.aclose()
            await http.aclose()
    print(f'共 {len(ledger.records)} 次呼叫，US${ledger.total:.4f}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='錄製 Gemini 的回應給 respx 重播')
    parser.add_argument('--env-file', type=Path, default=REPO_ROOT / '.env')
    parser.add_argument('--composer', default='http://127.0.0.1:3900')
    args = parser.parse_args()
    asyncio.run(main(args.env_file, args.composer))
