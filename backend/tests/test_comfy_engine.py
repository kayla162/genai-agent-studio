"""ComfyImageEngine：假的 ComfyClient 與 composer，不需要 GPU、ComfyUI 與資料庫。

確認每個 variant 送出的 workflow（提示詞、seed、底圖與遮罩）、事件、存檔的尺寸與網址、執行錯誤的重試。"""

import asyncio
import io
from collections.abc import Awaitable, Callable, Collection
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.adapters.comfyui import ComfyError, ComfyExecutionError, ComfyOutput, ComfyStats
from app.adapters.composer import PlateRect, PlateResult, PosterImages
from app.contract import (
    Brand,
    ComfyQueuedEvent,
    Product,
    PromptSpec,
    Render,
    RenderProgressEvent,
    UrlBackground,
)
from app.errors import AppError
from app.pipeline.comfy import ComfyImageEngine
from app.pipeline.memory import HeavyMemoryLock
from app.settings import Settings
from tests.fake_run import FakeRun
from tests.fixtures import load_fixture
from tests.test_memory_lock import FakeLock, Store

TIMELINE = load_fixture('timelines/selune-retry.json')
JOB_ID: str = TIMELINE['jobId']
#: 第 2 輪每個模板的 spec（selune-retry 有兩個模板）
SPECS: list[PromptSpec] = [
    Render.model_validate(r).spec
    for item in TIMELINE['events']
    if item['event']['type'] == 'render.completed' and item['event']['round'] == 2
    for r in item['event']['renders']
    if r['variant'] == 0
]
CATALOG = load_fixture('brands.json')
SELUNE = Brand.model_validate(next(b for b in CATALOG['brands'] if b['id'] == 'selune'))
SERUM = Product.model_validate(next(p for p in CATALOG['products'] if p['id'] == 'prod_selune_serum'))
#: 生成尺寸（Task 4 的 GENERATION_SIZES）
GEN = {'1:1': (1024, 1024), '4:3': (1152, 896), '4:5': (896, 1152), '9:16': (768, 1344), '16:9': (1344, 768)}

Outcome = tuple[int, int] | Exception


def png(size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, (180, 120, 130)).save(out, 'PNG')
    return out.getvalue()


def param(spec: PromptSpec, label: str) -> Any:
    return next(p.value for p in spec.injection.params if p.label == label)


class FakeComfy:
    def __init__(self, outcomes: list[Outcome] | None = None, missing: list[str] | None = None) -> None:
        self.outcomes = outcomes
        self.missing_items = missing or []
        self.ignored: Collection[tuple[str, str]] = ()
        self.uploads: list[tuple[str, bytes]] = []
        self.workflows: list[dict[str, Any]] = []
        self.freed = 0

    async def system_stats(self) -> ComfyStats:
        return ComfyStats(version='0.3.75', gpu='NVIDIA GeForce RTX 3060 Laptop GPU', vram_total=6441926656)

    async def missing(self, workflow: dict[str, Any], ignore: Collection[tuple[str, str]] = ()) -> list[str]:
        self.ignored = ignore
        return self.missing_items

    async def upload(self, name: str, data: bytes) -> str:
        self.uploads.append((name, data))
        return name

    async def run(
        self, workflow: dict[str, Any], run: FakeRun, on_progress: Callable[[str, int, int], Awaitable[None]]
    ) -> ComfyOutput:
        self.workflows.append(workflow)
        # 生成尺寸由底圖決定：預設回傳底圖的尺寸
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        await on_progress('3', 1, 1)  # 不是取樣節點：不算進度
        await on_progress('9', 1, 2)
        await on_progress('9', 2, 2)
        size = outcome or self.plate_size(workflow)
        return ComfyOutput(png=png(size), seconds=12.34)

    @staticmethod
    def plate_size(workflow: dict[str, Any]) -> tuple[int, int]:
        name = workflow['5']['inputs']['image']
        return next(GEN[s.canvas.ratio] for s in SPECS if name.endswith(f'_{s.template_id}_plate.png'))

    async def free(self) -> None:
        self.freed += 1


class FakeComposer:
    def __init__(self, warning: str | None = None) -> None:
        self.warning = warning
        self.plates: list[tuple[str, Product | None, PosterImages]] = []

    async def plate(self, spec: PromptSpec, product: Product | None, brand: Brand, images: PosterImages) -> PlateResult:
        self.plates.append((spec.template_id, product, images))
        w, h = GEN[spec.canvas.ratio]
        scale = max(spec.canvas.width / w, spec.canvas.height / h)
        return PlateResult(
            width=w,
            height=h,
            scale=scale,
            crop_x=(w * scale - spec.canvas.width) / 2,
            crop_y=(h * scale - spec.canvas.height) / 2,
            product_rect=PlateRect(100, 200, 300, 400),
            plate=b'plate:' + spec.template_id.encode(),
            mask=b'mask:' + spec.template_id.encode(),
            warning=self.warning,
        )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, image_mode='comfyui', agent_mode='sim', data_dir=tmp_path / 'data')


def engine(
    settings: Settings, comfy: FakeComfy, composer: FakeComposer | None = None, lock: HeavyMemoryLock | None = None
) -> ComfyImageEngine:
    return ComfyImageEngine(comfy, composer or FakeComposer(), settings, lock=lock)  # type: ignore[arg-type]


async def test_each_variant_is_one_prompt_with_its_seed_plate_and_mask(settings: Settings) -> None:
    comfy, composer, run = FakeComfy(), FakeComposer(), FakeRun(JOB_ID)
    out = await engine(settings, comfy, composer).render_round(JOB_ID, 2, SPECS, 2, SELUNE, SERUM, run)

    order = [(s.template_id, v) for s in SPECS for v in range(2)]
    assert list(out) == order
    # 每個模板畫一次底圖並上傳底圖與遮罩
    assert [t for t, _, _ in composer.plates] == [s.template_id for s in SPECS]
    assert comfy.uploads == [
        item
        for s in SPECS
        for item in (
            (param(s, 'plate_image'), b'plate:' + s.template_id.encode()),
            (param(s, 'mask_image'), b'mask:' + s.template_id.encode()),
        )
    ]
    assert comfy.ignored == {('5', 'image'), ('6', 'image')}
    for workflow, (template_id, v) in zip(comfy.workflows, order, strict=True):
        spec = next(s for s in SPECS if s.template_id == template_id)
        assert workflow['3']['inputs']['text'] == spec.positive_prompt
        assert workflow['4']['inputs']['text'] == spec.negative_prompt
        assert workflow['9']['inputs']['seed'] == param(spec, 'seed') + v
        assert workflow['5']['inputs']['image'] == param(spec, 'plate_image')
        assert workflow['6']['inputs']['image'] == param(spec, 'mask_image')

    queued = [e for e in run.events if isinstance(e, ComfyQueuedEvent)]
    assert [(e.template_id, e.prompt_id) for e in queued] == [(t, f'{JOB_ID}_r2_{t}_v{v}') for t, v in order]
    assert [next(p.value for p in e.injection.params if p.label == 'seed') for e in queued] == [
        param(next(s for s in SPECS if s.template_id == t), 'seed') + v for t, v in order
    ]
    progress = [(e.node, e.step, e.max_step) for e in run.events if isinstance(e, RenderProgressEvent)]
    assert progress == [('generate', 1, 2), ('generate', 2, 2)] * 4
    assert [m for m in run.messages('ok') if '生成完成' in m] == [f'✓ {t} v{v} 生成完成（12.3 秒）' for t, v in order]


async def test_backgrounds_are_saved_at_the_template_size_under_the_job(settings: Settings) -> None:
    out = await engine(settings, FakeComfy()).render_round(JOB_ID, 2, SPECS, 1, SELUNE, SERUM, FakeRun(JOB_ID))
    for spec in SPECS:
        background = out[(spec.template_id, 0)]
        name = f'bg-{spec.template_id}-r2-v0'
        assert background == UrlBackground(kind='url', url=f'/files/jobs/{JOB_ID}/{name}.png', includes_product=False)
        with Image.open(settings.data_dir / 'jobs' / JOB_ID / f'{name}.png') as img:
            assert img.size == (spec.canvas.width, spec.canvas.height)


async def test_an_execution_error_is_retried_once(settings: Settings) -> None:
    run = FakeRun(JOB_ID)
    comfy = FakeComfy([ComfyExecutionError('ComfyUI 執行失敗：KSampler（節點 9）RuntimeError：boom')])
    out = await engine(settings, comfy).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, run)
    assert len(out) == 1
    assert len(comfy.workflows) == 2
    assert any('重試一次' in m and 'KSampler' in m for m in run.messages('warn'))

    twice = FakeComfy([ComfyExecutionError('第一次'), ComfyExecutionError('ComfyUI 執行失敗：第二次')])
    with pytest.raises(AppError, match='ComfyUI 執行失敗：第二次'):
        await engine(settings, twice).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, FakeRun(JOB_ID))


async def test_other_comfyui_errors_are_not_retried(settings: Settings) -> None:
    comfy = FakeComfy([ComfyError('ComfyUI 沒有在 600 秒內完成（prompt p1）')])
    with pytest.raises(ComfyError, match='600 秒'):
        await engine(settings, comfy).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, FakeRun(JOB_ID))
    assert len(comfy.workflows) == 1


async def test_missing_nodes_or_models_stop_before_anything_is_sent(settings: Settings) -> None:
    comfy = FakeComfy(missing=['缺少節點 KSampler', '找不到 CheckpointLoaderSimple 的 ckpt_name：x.safetensors'])
    with pytest.raises(ComfyError) as info:
        await engine(settings, comfy).render_round(JOB_ID, 2, SPECS, 1, SELUNE, SERUM, FakeRun(JOB_ID))
    assert str(info.value) == (
        'ComfyUI 缺少 workflow 需要的項目：缺少節點 KSampler、找不到 CheckpointLoaderSimple 的 ckpt_name：x.safetensors'
        '（安裝方式見 comfyui/README.md）'
    )
    assert comfy.uploads == [] and comfy.workflows == []


async def test_the_plate_warning_is_logged(settings: Settings) -> None:
    run = FakeRun(JOB_ID)
    composer = FakeComposer(warning='商品尚未去背，背景依外框生成')
    await engine(settings, FakeComfy(), composer).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, run)
    assert f'{SPECS[0].template_id}：商品尚未去背，背景依外框生成' in run.messages('warn')


async def test_an_output_of_another_size_is_rejected(settings: Settings) -> None:
    comfy = FakeComfy([(512, 512)])
    with pytest.raises(ComfyError, match='ComfyUI 輸出的圖是 512 × 512'):
        await engine(settings, comfy).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, FakeRun(JOB_ID))


async def test_waits_for_a_running_cutout_and_holds_the_lock_while_rendering(settings: Settings) -> None:
    store = Store()
    lock = HeavyMemoryLock(lambda name, ttl: FakeLock(store, ttl, 'render'), ttl=0.3, poll=0.01)
    cutout = FakeLock(store, 0.3, 'cutout')
    assert await cutout.acquire(blocking=False)
    run = FakeRun(JOB_ID)

    async def finish_cutout() -> None:
        await asyncio.sleep(0.1)
        await cutout.release()

    comfy = FakeComfy()
    holders: list[object] = []
    original = comfy.run

    async def run_and_check(*args: Any) -> ComfyOutput:
        holders.append(store.owner)
        return await original(*args)

    comfy.run = run_and_check  # type: ignore[method-assign,assignment]
    await asyncio.gather(
        engine(settings, comfy, lock=lock).render_round(JOB_ID, 2, SPECS[:1], 1, SELUNE, SERUM, run), finish_cutout()
    )
    assert '等待商品去背完成' in run.messages()
    assert store.acquired == ['cutout', 'render']
    assert all(h is not None and h is not cutout for h in holders)
    assert store.owner is None


async def test_finish_frees_comfyui_only_when_configured(settings: Settings) -> None:
    comfy = FakeComfy()
    await engine(settings, comfy).finish(JOB_ID)
    assert comfy.freed == 0
    freeing = settings.model_copy(update={'comfyui_free_after_job': True})
    await engine(freeing, comfy).finish(JOB_ID)
    assert comfy.freed == 1
