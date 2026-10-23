"""呼叫真的 Gemini API（會產生費用）：需求拆解、Prompt 構建與 VLM 審查各一次，只檢查格式與護欄，不比對內容。

手動執行：uv run pytest -m live（一般的 pytest 不收集這些測試）。
key 取自環境變數 GEMINI_API_KEY，沒有時只讀 repo 根目錄 .env 的 GEMINI_API_KEY 這一個值；都沒有時略過。
需要測試啟動的 composer（需要字型）；不需要資料庫。
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import get_args

import pytest
from dotenv import dotenv_values

from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiClient
from app.brands import load_brands
from app.contract import ProceduralBackground, RagHit, Render, Tone
from app.pipeline.gemini import GeminiAgent, GeminiReviewer
from app.pipeline.ports import SpecRequest
from app.pipeline.review import ComposerPosters
from app.settings import REPO_ROOT, Settings
from app.templates import get_template
from app.usage import MemoryLedger, Pricing
from tests.fake_run import FakeRun
from tests.fixtures import BRANDS_DIR

LOADED = {b.brand.id: b for b in load_brands(BRANDS_DIR)[0]}['selune']
TEXT = '週年慶 10/15–11/15 主打買一送一，要溫柔療癒的感覺'


def live_key() -> str | None:
    env = REPO_ROOT / '.env'
    return os.environ.get('GEMINI_API_KEY') or (dotenv_values(env).get('GEMINI_API_KEY') if env.is_file() else None)


KEY = live_key()
# skipif 在準備 fixture（例如啟動 composer）之前判斷：沒有 key 時什麼都不做
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not KEY, reason='沒有 GEMINI_API_KEY（環境變數或 repo 根目錄的 .env），略過 live 測試'),
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None, image_mode='sim', agent_mode='gemini', gemini_api_key=KEY or '', data_dir=tmp_path / 'data'
    )


@pytest.fixture
async def gemini(settings: Settings) -> AsyncIterator[tuple[GeminiClient, MemoryLedger]]:
    ledger = MemoryLedger(Pricing.load(REPO_ROOT / 'pricing.yaml'))
    client = GeminiClient(settings, ledger)
    yield client, ledger
    await client.aclose()
    print(f'\nGemini：{len(ledger.records)} 次呼叫，US${ledger.total:.4f}')


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[ComposerClient]:
    client = ComposerClient(composer_url)
    yield client
    await client.aclose()


async def test_live_brief_spec_and_review(
    settings: Settings, gemini: tuple[GeminiClient, MemoryLedger], composer: ComposerClient
) -> None:
    client, ledger = gemini
    brand, product = LOADED.brand, LOADED.samples[0]
    agent = GeminiAgent(client, composer, settings)
    run = FakeRun('job_live')

    brief = await agent.parse_brief(brand, TEXT, product)
    assert brief.tone in get_args(Tone)
    assert brief.product_name == product.name
    assert len(brief.selling_points) <= 3

    hits = [
        RagHit(chunk_id=c.id, source=c.source, section=c.section, tag=c.tag, text=c.text, vector_score=0.9)
        for c in brand.guideline_chunks
        if c.tag in ('color', 'law', 'layout')
    ]
    request = SpecRequest(
        'job_live', 1, brand, product, brief, get_template('ig-post'), 'comfyui', 123456789,
        [h.chunk_id for h in hits], [], text=TEXT, hits=hits,
    )  # fmt: skip
    spec = await agent.build_spec(request, run)
    assert len(spec.layout) == 8
    assert all(line.strip() for line in spec.copy_.headline)
    assert spec.copy_.badge.main == brief.offer or brief.offer is None

    render = Render(
        id='job_live_r1_ig-post_v0', job_id='job_live', round=1, template_id='ig-post', variant=0,
        background=ProceduralBackground(kind='procedural', seed=1, palette=spec.palette, style=brand.id),
        spec=spec, score=None, passed=None, checks=[],
    )  # fmt: skip
    poster = await ComposerPosters(composer, settings).compose('job_live', render, product, brand)
    result = await GeminiReviewer(client, composer, settings).review(brand, render, 7, poster, run)
    assert [c.id for c in result.checks][-3:] == ['vlm_exaggeration', 'vlm_occlusion', 'vlm_quality']
    assert not any('模擬' in c.value for c in result.checks)
    assert {kind for _, kind, *_ in ledger.records} >= {'brief', 'spec', 'vlm'}
