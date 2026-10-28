"""Plan 7 規格 §2 的實驗：以真的 ComfyUI 生成背景，量時間、記憶體與背景色系。

用法（在 backend/，需要啟動中的 ComfyUI 與 composer：在 web/ 執行 npm run composer）：

    uv run python -m scripts.comfy_experiment <probe|run|palette|all> [--limit N] [--cfg C] [--comfyui URL]

- probe：ComfyUI 的版本、GPU 與 workflow 需要的節點與模型。
- run：3 個品牌 × 5 個模板各生成一張（--limit 限制張數）：每張的秒數（第一張含載入模型，另外列出）、
  GPU 與系統記憶體的尖峰、背景色系（composer 的 /render 量測），並畫出審查用海報供人工檢查商品邊緣。
- palette：正面提示詞刻意指定偏離品牌色系的顏色（螢光綠、螢光粉紅、深藍），應該全部不通過。
- 報告寫到 data/experiments/plan7-<時間>/report.json（data/ 不進 git），背景與海報存在同一個資料夾；終端機印出摘要。
- 提示詞用模擬 Agent（composer 的 /sim/prompt），不需要 Gemini key。
"""

import argparse
import asyncio
import ctypes
import json
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.adapters.comfyui import ComfyClient
from app.adapters.composer import ComposerClient, PosterImages
from app.brands import LoadedBrand, load_brands
from app.contract import Brand, JobEvent, LogLevel, LogSource, Product, PromptSpec, RagHit, Render, TemplateId
from app.pipeline.comfy import ComfyImageEngine, load_workflow
from app.pipeline.ports import SpecRequest
from app.settings import REPO_ROOT, Settings
from app.templates import get_template
from app.visual_style import choose_visual_style

BRANDS = ('selune', 'misty-isle', 'my-brand-01')
TEMPLATES: tuple[TemplateId, ...] = ('ecom-main', 'scene', 'ig-post', 'story', 'banner')
TEXT = '週年慶 10/15–11/15 主打買一送一，要溫柔療癒的感覺'
#: palette 實驗：正面提示詞加上偏離品牌色系的顏色
OFF_BRAND = {
    'neon-green': 'saturated neon green background, fluorescent lime green light',
    'fluorescent-pink': 'fluorescent hot pink background, neon magenta light',
    'deep-blue': 'deep saturated cobalt blue background, electric blue light',
}


def sample_product(loaded: LoadedBrand) -> Product:
    """沒有示範商品的品牌（例如 Kayla 精緻少女）用 serum 向量素材建立暫時的商品（不寫入資料庫）。"""
    if loaded.samples:
        return loaded.samples[0]
    return Product.model_validate(
        {
            'id': f'prod_{loaded.brand.id}_experiment', 'brandId': loaded.brand.id, 'name': '玻尿酸保濕精華 30ml',
            'features': ['玻尿酸', '溫和配方', '無香精'], 'price': {'sale': 890, 'original': 1190},
            'photo': {'source': 'sample', 'art': 'serum'}, 'cutout': None, 'createdAt': '2026-10-23T00:00:00.000Z',
        }
    )  # fmt: skip


def hits_of(brand: Brand) -> list[RagHit]:
    return [
        RagHit(chunk_id=c.id, source=c.source, section=c.section, tag=c.tag, text=c.text, vector_score=0.9)
        for c in brand.guideline_chunks
        if c.tag in ('color', 'law', 'layout') and not c.id.endswith('-alt')
    ]


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]


def system_used_gb() -> float:
    """Windows 的系統記憶體使用量（GB）；其他系統回傳 0。"""
    try:
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return 0.0
    return float(status.ullTotalPhys - status.ullAvailPhys) / 2**30


def gpu_used_gb() -> float:
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return int(out.stdout.split()[0]) / 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0.0


@dataclass
class Sampler:
    """每秒記錄一次 GPU 與系統記憶體，取尖峰。"""

    peak_gpu: float = 0.0
    peak_system: float = 0.0
    baseline_system: float = field(default_factory=system_used_gb)
    _stop: threading.Event = field(default_factory=threading.Event)

    def _loop(self) -> None:
        while not self._stop.wait(1):
            self.peak_gpu = max(self.peak_gpu, gpu_used_gb())
            self.peak_system = max(self.peak_system, system_used_gb())

    def __enter__(self) -> 'Sampler':
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()


class QuietRun:
    job_id = 'job_experiment'

    def __init__(self) -> None:
        self.logs: list[str] = []

    async def emit(self, event: JobEvent) -> None:
        return None

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        self.logs.append(message)
        if level != 'info' or '生成完成' in message:
            print(f'  [{source}] {message}')

    async def pace(self, ms: float) -> None:
        return None

    async def wait(self, awaitable: Any, note: str | None = None) -> Any:
        return await awaitable

    def seconds(self) -> list[float]:
        return [float(m.rsplit('（', 1)[1].split(' ')[0]) for m in self.logs if '生成完成' in m]


class Experiment:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = REPO_ROOT / 'data' / 'experiments' / f'plan7-{datetime.now():%Y%m%d-%H%M%S}'
        self.settings = Settings(
            _env_file=None,
            image_mode='comfyui',
            agent_mode='sim',
            comfyui_url=args.comfyui,
            data_dir=self.out,
        )
        self.composer = ComposerClient(args.composer, timeout=120)
        self.comfy = ComfyClient(self.settings)
        self.engine = ComfyImageEngine(self.comfy, self.composer, self.settings)
        self.brands: dict[str, LoadedBrand] = {b.brand.id: b for b in load_brands(REPO_ROOT / 'brands')[0]}
        self.report: dict[str, Any] = {'startedAt': datetime.now().isoformat(), 'cfg': args.cfg}

    async def spec(self, brand: Brand, product: Product, template_id: TemplateId, job_id: str) -> PromptSpec:
        brief = await self.composer.sim_brief(brand, product, TEXT)
        hits = hits_of(brand)
        request = SpecRequest(
            job_id, 1, brand, product, brief, get_template(template_id), 'comfyui', 20261024,
            [h.chunk_id for h in hits], [],
            choose_visual_style(brand, brief.tone, None).style, text=TEXT, hits=hits,
        )  # fmt: skip
        spec = await self.composer.sim_prompt(request, flawed=False)
        if self.args.cfg is None:
            return spec
        # 比較 cfg：覆寫注入的參數（cfg 1 時負面提示詞幾乎沒有作用）
        params = [
            p.model_copy(update={'value': self.args.cfg}) if p.label == 'cfg' else p for p in spec.injection.params
        ]
        return spec.model_copy(update={'injection': spec.injection.model_copy(update={'params': params})})

    async def generate(self, job_id: str, spec: PromptSpec, brand: Brand, product: Product) -> dict[str, Any]:
        """生成一張背景，畫出審查用海報，回傳秒數與背景色系。"""
        run = QuietRun()
        out = await self.engine.render_round(job_id, 1, [spec], 1, brand, product, run)
        background = out[(spec.template_id, 0)]
        render = Render(
            id=f'{job_id}_r1_{spec.template_id}_v0', job_id=job_id, round=1, template_id=spec.template_id, variant=0,
            background=background, spec=spec, score=None, passed=None, checks=[],
        )  # fmt: skip
        bg_path = self.out / 'jobs' / job_id / f'bg-{spec.template_id}-r1-v0.png'
        poster = await self.composer.render(render, product, brand, PosterImages(background=bg_path.read_bytes()))
        (self.out / f'{job_id}-{spec.template_id}-poster.png').write_bytes(poster.png)
        palette = poster.background
        return {
            'brand': brand.id,
            'template': spec.template_id,
            'seconds': run.seconds()[0],
            'offShare': palette.off_share if palette else None,
            'offHex': palette.off_hex if palette else None,
            'background': str(bg_path.relative_to(REPO_ROOT)),
        }

    async def probe(self) -> None:
        stats = await self.comfy.system_stats()
        workflow, ignore = load_workflow(self.settings.comfyui_workflows_dir)
        missing = await self.comfy.missing(workflow, ignore=ignore)
        vram = round(stats.vram_total / 2**30, 1)
        self.report['probe'] = {'version': stats.version, 'gpu': stats.gpu, 'vramGb': vram, 'missing': missing}
        print(f'ComfyUI {stats.version}・{stats.gpu}・VRAM {stats.vram_total / 2**30:.1f} GB')
        print('缺少：' + ('、'.join(missing) if missing else '無'))

    async def run(self) -> None:
        results: list[dict[str, Any]] = []
        with Sampler() as sampler:
            for brand_id in BRANDS:
                loaded = self.brands[brand_id]
                product = sample_product(loaded)
                for template_id in TEMPLATES:
                    if self.args.limit and len(results) >= self.args.limit:
                        break
                    spec = await self.spec(loaded.brand, product, template_id, f'job_exp_{brand_id.replace("-", "_")}')
                    result = await self.generate(f'job_exp_{brand_id.replace("-", "_")}', spec, loaded.brand, product)
                    results.append(result)
        seconds = [r['seconds'] for r in results]
        self.report['run'] = {
            'results': results,
            'firstSeconds': seconds[0] if seconds else None,
            'meanSeconds': statistics.mean(seconds[1:]) if len(seconds) > 1 else None,
            'maxSeconds': max(seconds[1:]) if len(seconds) > 1 else None,
            'peakGpuGb': round(sampler.peak_gpu, 2),
            'peakSystemGb': round(sampler.peak_system, 2),
            'baselineSystemGb': round(sampler.baseline_system, 2),
            'paletteFails': [r for r in results if r['offShare'] is not None and r['offShare'] > 0.15],
        }
        r = self.report['run']
        print(f'\n{len(results)} 張：第一張 {r["firstSeconds"]} 秒（含載入模型）')
        print(f'其後平均 {r["meanSeconds"]} 秒、最長 {r["maxSeconds"]} 秒')
        print(f'記憶體尖峰：GPU {r["peakGpuGb"]} GB、系統 {r["peakSystemGb"]} GB（開始時 {r["baselineSystemGb"]} GB）')
        print(
            '背景色系 > 15%：'
            + ('、'.join(f'{x["brand"]}/{x["template"]} {x["offShare"]:.0%}' for x in r['paletteFails']) or '無')
        )

    async def palette(self) -> None:
        results: list[dict[str, Any]] = []
        for brand_id in BRANDS:
            loaded = self.brands[brand_id]
            product = sample_product(loaded)
            for name, extra in OFF_BRAND.items():
                spec = await self.spec(
                    loaded.brand, product, 'ig-post', f'job_off_{brand_id.replace("-", "_")}_{name.replace("-", "_")}'
                )
                positive = f'{extra}, {spec.positive_prompt}'
                params = [
                    p.model_copy(update={'value': positive}) if p.label == 'positive_prompt' else p
                    for p in spec.injection.params
                ]
                spec = spec.model_copy(
                    update={
                        'positive_prompt': positive,
                        'injection': spec.injection.model_copy(update={'params': params}),
                    }
                )
                result = await self.generate(spec.job_id, spec, loaded.brand, product)
                results.append({**result, 'offBrand': name})
        self.report['palette'] = {'results': results, 'caught': sum(1 for r in results if (r['offShare'] or 0) > 0.3)}
        print(f'\n刻意偏離色系：{len(results)} 張，判定不通過 {self.report["palette"]["caught"]} 張')
        for r in results:
            print(f'  {r["brand"]}/{r["offBrand"]}：色系外 {r["offShare"]:.0%}（{r["offHex"]}）')

    async def close(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / 'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n報告：{self.out / "report.json"}')
        await self.comfy.aclose()
        await self.composer.aclose()


async def main(args: argparse.Namespace) -> None:
    experiment = Experiment(args)
    started = time.monotonic()
    try:
        if args.command in ('probe', 'all'):
            await experiment.probe()
        if args.command in ('run', 'all'):
            await experiment.run()
        if args.command in ('palette', 'all'):
            await experiment.palette()
    finally:
        experiment.report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        await experiment.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['probe', 'run', 'palette', 'all'])
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--cfg', type=float, default=None, help='覆寫 workflow 的 cfg（比較用）')
    parser.add_argument('--comfyui', default='http://127.0.0.1:8188')
    parser.add_argument('--composer', default='http://127.0.0.1:3900')
    asyncio.run(main(parser.parse_args()))
