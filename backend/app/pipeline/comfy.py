"""真實版的生圖（IMAGE_MODE=comfyui，Plan 7 規格 §4.6）：ComfyUI 依商品底圖生成背景。

每一輪：
1. 檢查 ComfyUI 的連線，以及 workflow 用到的節點與模型（缺少時任務失敗，不送出任何 prompt）。
2. 每個模板：composer 的 /plate 畫出商品底圖與遮罩，上傳到 ComfyUI。
3. 每個 variant 一個 prompt，依序送出（只有一張 GPU）：參數就是 PromptSpec.injection（seed 加上 variant 編號），
   送出前送一則 comfy.queued；取樣節點的進度換成 render.progress（generate）。執行錯誤時重試一次。
生圖期間持有 heavy-memory 鎖（商品去背在鎖釋放後才開始，Plan 7 規格 §4.7）；任務結束時依
COMFYUI_FREE_AFTER_JOB 請 ComfyUI 釋放記憶體（finish）。

4. 輸出圖以 cover 方式放大（Lanczos）並置中裁切成模板尺寸，存到 data/jobs/{jobId}/bg-{模板}-r{輪}-v{variant}.png。
   商品像素不在這張圖裡：composer 與瀏覽器把原始去背圖疊在同一個位置（includesProduct: false）。
"""

import asyncio
import contextlib
import copy
import io
import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from app.adapters.comfyui import ComfyClient, ComfyError, ComfyExecutionError
from app.adapters.composer import ComposerClient, ComposerError, PlateResult, PosterImages
from app.contract import (
    Brand,
    ComfyInjection,
    ComfyQueuedEvent,
    Product,
    PromptSpec,
    RenderBackground,
    RenderProgressEvent,
    TemplateId,
    UrlBackground,
)
from app.errors import AppError
from app.files import poster_file
from app.pipeline.memory import HeavyMemoryLock
from app.pipeline.ports import RunContext
from app.pipeline.review import product_image
from app.settings import REPO_ROOT, Settings

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = REPO_ROOT / 'comfyui' / 'workflows'
#: 參數對照表（web/src/lib/agent/comfy.ts 匯出、與這個檔案相同）
TABLE_FILE = 'product_scene_v1.params.json'
#: 回報進度的節點類型（取樣）；其他節點很快，不回報
SAMPLER_NODES = frozenset({'KSampler', 'KSamplerAdvanced', 'SamplerCustom', 'SamplerCustomAdvanced'})
#: 底圖與遮罩：每個任務上傳的檔名，不在 ComfyUI 的模型清單裡
IMAGE_LABELS = frozenset({'plate_image', 'mask_image'})
PLATE_FAILED = '排版服務（composer）無法產生商品底圖：'
MISSING_PRODUCT_IMAGE = '無法產生商品底圖：'


def _with_seed(injection: ComfyInjection, seed: int) -> ComfyInjection:
    params = [p.model_copy(update={'value': seed}) if p.label == 'seed' else p for p in injection.params]
    return injection.model_copy(update={'params': params})


def _fill(workflow: dict[str, Any], injection: ComfyInjection) -> dict[str, Any]:
    """把注入的參數寫進 workflow 的副本。"""
    out = copy.deepcopy(workflow)
    for p in injection.params:
        out[p.node_id]['inputs'][p.input] = p.value
    return out


def _fit(data: bytes, width: int, height: int) -> tuple[int, int, bytes]:
    """以 cover 方式放大（Lanczos）並置中裁切成 width × height，回傳原始尺寸與 PNG。
    與 composer 的 plateGeometry 相同，商品的位置才會與原始去背圖對齊。"""
    with Image.open(io.BytesIO(data)) as img:
        w, h = img.size
        scale = max(width / w, height / h)
        resized = img.convert('RGB').resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    out = io.BytesIO()
    resized.crop((left, top, left + width, top + height)).save(out, 'PNG')
    return w, h, out.getvalue()


class ComfyImageEngine:
    def __init__(
        self,
        comfy: ComfyClient,
        composer: ComposerClient,
        settings: Settings,
        workflows_dir: Path = WORKFLOWS_DIR,
        lock: HeavyMemoryLock | None = None,
    ) -> None:
        self.comfy = comfy
        self.composer = composer
        self.settings = settings
        self.lock = lock
        table = json.loads((workflows_dir / TABLE_FILE).read_text(encoding='utf-8'))
        self.workflow: dict[str, Any] = json.loads((workflows_dir / table['workflow']).read_text(encoding='utf-8'))
        self.ignore = frozenset((p['nodeId'], p['input']) for p in table['params'] if p['label'] in IMAGE_LABELS)
        self.samplers = frozenset(i for i, n in self.workflow.items() if n['class_type'] in SAMPLER_NODES)

    async def render_round(
        self,
        job_id: str,
        round: int,
        specs: list[PromptSpec],
        variants: int,
        brand: Brand,
        product: Product,
        run: RunContext,
    ) -> dict[tuple[TemplateId, int], RenderBackground]:
        stats = await self.comfy.system_stats()
        await run.log('comfy', f'ComfyUI {stats.version}・{stats.gpu}・VRAM {stats.vram_total / 2**30:.1f} GB')
        missing = await self.comfy.missing(self.workflow, ignore=self.ignore)
        if missing:
            raise ComfyError(f'ComfyUI 缺少 workflow 需要的項目：{"、".join(missing)}（安裝方式見 comfyui/README.md）')

        images = PosterImages(
            product=await asyncio.to_thread(product_image, self.settings, product, MISSING_PRODUCT_IMAGE)
        )

        async def waiting() -> None:
            await run.log('comfy', '等待商品去背完成')

        out: dict[tuple[TemplateId, int], RenderBackground] = {}
        async with self.lock.hold(waiting, run) if self.lock else contextlib.nullcontext():
            for spec in specs:
                plate = await self._plate(spec, product, brand, images, run)
                for v in range(variants):
                    out[(spec.template_id, v)] = await self._variant(job_id, round, spec, v, plate, run)
        return out

    async def finish(self, job_id: str) -> None:
        """任務結束（完成、失敗或取消）：COMFYUI_FREE_AFTER_JOB 時請 ComfyUI 釋放模型與記憶體。失敗只記錄。"""
        if not self.settings.comfyui_free_after_job:
            return
        try:
            await self.comfy.free()
        except ComfyError:
            logger.warning('ComfyUI 無法釋放記憶體：job_id=%s', job_id, exc_info=True)

    async def _plate(
        self, spec: PromptSpec, product: Product, brand: Brand, images: PosterImages, run: RunContext
    ) -> PlateResult:
        try:
            plate = await self.composer.plate(spec, product, brand, images)
        except ComposerError as error:
            raise AppError(f'{PLATE_FAILED}{error}') from error
        if plate.warning:
            await run.log('comfy', f'{spec.template_id}：{plate.warning}', 'warn')
        names = {p.label: str(p.value) for p in spec.injection.params if p.label in IMAGE_LABELS}
        await self.comfy.upload(names['plate_image'], plate.plate)
        await self.comfy.upload(names['mask_image'], plate.mask)
        return plate

    async def _variant(
        self, job_id: str, round: int, spec: PromptSpec, v: int, plate: PlateResult, run: RunContext
    ) -> UrlBackground:
        seed = int(next(p.value for p in spec.injection.params if p.label == 'seed')) + v
        injection = _with_seed(spec.injection, seed)
        await run.emit(
            ComfyQueuedEvent(
                type='comfy.queued',
                round=round,
                template_id=spec.template_id,
                prompt_id=f'{job_id}_r{round}_{spec.template_id}_v{v}',
                injection=injection,
            )
        )

        async def on_progress(node: str, step: int, total: int) -> None:
            if node in self.samplers:
                await run.emit(
                    RenderProgressEvent(type='render.progress', round=round, node='generate', step=step, max_step=total)
                )

        workflow = _fill(self.workflow, injection)
        try:
            output = await self.comfy.run(workflow, run, on_progress)
        except ComfyExecutionError as error:
            await run.log('comfy', f'{spec.template_id} v{v}：{error}，重試一次', 'warn')
            output = await self.comfy.run(workflow, run, on_progress)

        width, height = spec.canvas.width, spec.canvas.height
        w, h, png = await asyncio.to_thread(_fit, output.png, width, height)
        if (w, h) != (plate.width, plate.height):
            # 尺寸不同時放大與裁切的方式也不同，商品的位置會對不上原始去背圖
            raise ComfyError(f'ComfyUI 輸出的圖是 {w} × {h}，與商品底圖的 {plate.width} × {plate.height} 不同')
        target, url = poster_file(self.settings, job_id, f'bg-{spec.template_id}-r{round}-v{v}')
        await asyncio.to_thread(_write, target, png)
        await run.log('comfy', f'✓ {spec.template_id} v{v} 生成完成（{output.seconds:.1f} 秒）', 'ok')
        return UrlBackground(kind='url', url=url, includes_product=False)


def _write(target: Path, png: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png)
