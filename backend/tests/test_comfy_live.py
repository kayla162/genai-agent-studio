"""連本機真的 ComfyUI（需要 GPU 與 comfyui/README.md 的模型）：每個模板生成一張背景，檢查尺寸、檔案與秒數。

手動執行：uv run pytest -m live（一般的 pytest 不收集這些測試）。
ComfyUI 的位址取自環境變數 COMFYUI_URL（預設 http://127.0.0.1:8188）；連不上時略過。
需要測試啟動的 composer（商品底圖）；不需要資料庫。
"""

import os
import re
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.adapters.comfyui import ComfyClient
from app.adapters.composer import ComposerClient
from app.brands import load_brands
from app.contract import TEMPLATE_IDS, Canvas, Render, UrlBackground
from app.pipeline.comfy import ComfyImageEngine
from app.settings import Settings
from app.templates import get_template
from tests.fake_run import FakeRun
from tests.fixtures import BRANDS_DIR, load_fixture

URL = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')


def reachable() -> bool:
    try:
        return httpx.get(f'{URL}/system_stats', timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


# skipif 在準備 fixture（例如啟動 composer）之前判斷：沒有 ComfyUI 時什麼都不做
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not reachable(), reason=f'ComfyUI 沒有回應（{URL}），略過 live 測試'),
]

LOADED = {b.brand.id: b for b in load_brands(BRANDS_DIR)[0]}['selune']
SERUM = next(p for p in LOADED.samples if p.id == 'prod_selune_serum')
#: selune-retry 第 2 輪的 IG 貼文：其他模板沿用它的提示詞，換成各模板的畫布與版面
BASE = next(
    Render.model_validate(r).spec
    for item in load_fixture('timelines/selune-retry.json')['events']
    if item['event']['type'] == 'render.completed' and item['event']['round'] == 2
    for r in item['event']['renders']
    if r['templateId'] == 'ig-post' and r['variant'] == 0
)


async def test_generates_one_background_per_template(composer_url: str, tmp_path: Path) -> None:
    settings = Settings(_env_file=None, image_mode='comfyui', agent_mode='sim', comfyui_url=URL, data_dir=tmp_path)
    composer = ComposerClient(composer_url)
    specs = []
    for template_id in TEMPLATE_IDS:
        t = get_template(template_id)
        params = [
            p.model_copy(update={'value': str(p.value).replace('_ig-post_', f'_{template_id}_')})
            if p.label in ('plate_image', 'mask_image')
            else p
            for p in BASE.injection.params
        ]
        specs.append(
            BASE.model_copy(
                update={
                    'template_id': template_id,
                    'canvas': Canvas(width=t.width, height=t.height, ratio=t.ratio),
                    'layout': await composer.layout(template_id),
                    'injection': BASE.injection.model_copy(update={'params': params}),
                }
            )
        )
    comfy = ComfyClient(settings)
    run = FakeRun('job_live')
    try:
        out = await ComfyImageEngine(comfy, composer, settings).render_round(
            'job_live', 1, specs, 1, LOADED.brand, SERUM, run
        )
    finally:
        await comfy.aclose()
        await composer.aclose()
    seconds = []
    for spec in specs:
        path = tmp_path / 'jobs' / 'job_live' / f'bg-{spec.template_id}-r1-v0.png'
        background = out[(spec.template_id, 0)]
        assert isinstance(background, UrlBackground) and background.url.endswith(path.name)
        with Image.open(path) as img:
            assert img.size == (spec.canvas.width, spec.canvas.height)
        log = next(m for m in run.messages('ok') if m.startswith(f'✓ {spec.template_id} v0'))
        found = re.search(r'（([\d.]+) 秒）', log)
        assert found is not None
        seconds.append((spec.template_id, float(found.group(1))))
    print('\nComfyUI：' + '、'.join(f'{t} {s:.1f} 秒' for t, s in seconds))
