"""Plan 6B 規格 §2 的實驗：以真的 Gemini API 量測結構化輸出、轉錄與錯字、VLM 判讀、穩定性、用量與思考程度。

用法（在 backend/，需要 GEMINI_API_KEY 與執行中的 composer：在 web/ 執行 npm run composer）：

    uv run python -m scripts.gemini_experiment <probe|spec|ocr|vlm|stability|all> [選項]

    --thinking low|high   所有呼叫改用這個思考程度（預設依 app/adapters/gemini.py 的 THINKING）
    --limit N             只跑前 N 個（品牌 × 模板）組合，控制費用
    --repeat N            spec 每個組合構建幾次（預設 2）
    --offline             不呼叫 Gemini，以假的回應跑完整個流程（檢查腳本本身）
    --budget 美元          累計費用達到這個金額時停止送出新的呼叫（預設 3；並行中的呼叫仍會完成）
    --env-file 路徑        key 不在環境變數時，只讀這個檔案的 GEMINI_API_KEY（預設 repo 根目錄的 .env）
    --composer 網址        預設 http://127.0.0.1:3900

報告寫到 data/experiments/plan6b-<時間>.json，並在終端機印出摘要。會產生費用：all 約呼叫 110 次。
組合之間並行（同時最多 GEMINI_CONCURRENCY 個 Gemini 呼叫）；Gemini 很慢時可以用環境變數 GEMINI_TIMEOUT_SECONDS、
GEMINI_MAX_RETRIES 放寬逾時與重試次數（Settings 會讀環境變數）。
"""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.adapters import gemini as gemini_adapter
from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiCall, GeminiClient, LlmClient
from app.brands import LoadedBrand, load_brands
from app.contract import (
    Brand,
    JobEvent,
    LogLevel,
    LogSource,
    ProceduralBackground,
    Product,
    PromptSpec,
    RagHit,
    Render,
    TemplateId,
)
from app.errors import BudgetExceeded
from app.pipeline.gemini import GeminiReviewer, load_prompt
from app.pipeline.gemini_types import SpecDraft, VlmVerdict
from app.pipeline.ports import ComposedPoster, ReviewResult, SpecRequest
from app.pipeline.review import ComposerPosters
from app.settings import REPO_ROOT, Settings
from app.templates import CHANNEL_TEMPLATES, get_template
from app.usage import MemoryLedger, Pricing, UsageScope, usd
from app.visual_style import choose_visual_style

BRANDS = ('selune', 'misty-isle', 'my-brand-01')
VLM_CHECKS = ('vlm_exaggeration', 'vlm_occlusion', 'vlm_quality')
TEXT = '週年慶 10/15–11/15 主打買一送一，要溫柔療癒的感覺'
EXAGGERATED = '三天見效・全台第一'


@dataclass
class Report:
    results: dict[str, Any] = field(default_factory=dict)
    #: 每次 generate（含重試與格式重問）的種類與秒數
    timings: list[dict[str, Any]] = field(default_factory=list)


class TimingClient(LlmClient):
    """記錄每次 generate 花的時間（並行時 ledger 的紀錄會交錯，所以時間另外記）。"""

    def __init__(self, inner: LlmClient, report: Report) -> None:
        self.inner = inner
        self.report = report

    async def generate[T: BaseModel](self, call: GeminiCall[T], run: Any) -> T:
        started = time.monotonic()
        try:
            return await self.inner.generate(call, run)
        finally:
            self.report.timings.append({'kind': call.kind, 'seconds': round(time.monotonic() - started, 2)})


class CappedLedger(MemoryLedger):
    """實驗用的用量：累計費用達到 budget 時拒絕新的呼叫（0 為不設上限）。"""

    def __init__(self, pricing: Pricing, budget: float) -> None:
        super().__init__(pricing)
        self.budget = budget

    async def check(self, scope: UsageScope, model: str) -> None:
        await super().check(scope, model)
        if self.budget > 0 and self.total >= self.budget:
            raise BudgetExceeded(f'實驗費用已達上限（{usd(self.budget)}，已用 {usd(self.total)}）')


class ExperimentRun:
    """記錄 log（格式錯誤的重問次數）；不檢查取消。"""

    job_id = 'job_experiment'

    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []

    async def emit(self, event: JobEvent) -> None:
        return None

    async def log(self, source: LogSource, message: str, level: LogLevel = 'info') -> None:
        self.logs.append((level, message))

    async def pace(self, ms: float) -> None:
        return None

    async def wait(self, awaitable: Any, note: str | None = None) -> Any:
        return await awaitable

    def format_retries(self) -> int:
        return sum('回應格式錯誤' in m for _, m in self.logs)


class OfflineClient(LlmClient):
    """--offline：不呼叫 Gemini。Prompt 構建回傳預設文案與版型，VLM 回傳海報上的文案（不含刻意的錯字）。"""

    def __init__(self) -> None:
        self.next_spec: PromptSpec | None = None

    async def generate[T: BaseModel](self, call: GeminiCall[T], run: Any) -> T:
        if call.schema is SpecDraft and self.next_spec is not None:
            c = self.next_spec.copy_
            layout = [{'id': b.id, 'bbox': list(b.bbox)} for b in self.next_spec.layout]
            draft = {
                'headline': list(c.headline),
                'subhead': c.subhead,
                'features': c.features,
                'badge': c.badge.to_json(),
                'priceLabel': c.price.label,
                'layout': layout,
                'scene': 'product on a styled surface, soft light',
                'negativeExtra': '',
                'rationale': '離線測試',
            }
            return call.schema.model_validate(draft)
        if call.schema is VlmVerdict:
            payload = json.loads(next(p for p in call.parts if isinstance(p, str)))
            lines = payload.get('expected', [])
            ok = {'status': 'pass', 'reason': ''}
            verdict = {
                'lines': lines, 'exaggeration': {**ok, 'phrases': []}, 'occlusion': {**ok, 'elements': []},
                'quality': {**ok, 'issues': []},
            }  # fmt: skip
            return call.schema.model_validate(verdict)
        raise RuntimeError(f'離線模式不支援 {call.kind}')


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


def with_first_char(spec: PromptSpec, char: str) -> PromptSpec:
    """把標題第 1 行的第一個字換掉（刻意的錯字；「这」是海報字型沒有的字，畫成方塊）。"""
    first, second = spec.copy_.headline
    copy = spec.copy_.model_copy(update={'headline': (f'{char}{first[1:]}', second)})
    return spec.model_copy(update={'copy_': copy})


def drawn_text(spec: PromptSpec, brand: Brand) -> list[str]:
    """離線模式的「轉錄」：海報上畫出的文字（與 composer 的 scene.ts 大致相同）。"""
    c = spec.copy_
    # 與 web 的 logoFor 相同：品牌名稱中的拉丁字，沒有時用全名
    match = re.search(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&.' -]*[A-Za-zÀ-ÿ]", brand.name)
    latin = match.group(0) if match else ''
    return [
        latin or brand.name, *c.headline, c.subhead, *c.features, c.badge.top, c.badge.main, c.badge.sub,
        f'{c.product_name}｜{c.price.label}', 'NT$', f'{c.price.sale:,}', f'原價 NT${c.price.original:,}',
        c.disclaimer, '立即選購 →',
    ]  # fmt: skip


class Experiment:
    def __init__(self, args: argparse.Namespace, settings: Settings, report: Report) -> None:
        self.args = args
        self.settings = settings
        self.report = report
        self.ledger = CappedLedger(Pricing.load(REPO_ROOT / 'pricing.yaml'), args.budget)
        self.offline = OfflineClient() if args.offline else None
        self.gemini = None if args.offline else GeminiClient(settings, self.ledger)
        self.client: LlmClient = TimingClient(self.offline or self.gemini, report)  # type: ignore[arg-type]
        self.composer = ComposerClient(args.composer)
        self.posters = ComposerPosters(self.composer, settings)
        loaded = {b.brand.id: b for b in load_brands(REPO_ROOT / 'brands')[0]}
        self.brands = [(loaded[i].brand, sample_product(loaded[i])) for i in BRANDS if i in loaded]
        combos = [(b, p, t.id) for b, p in self.brands for t in CHANNEL_TEMPLATES]
        self.combos = combos[: args.limit] if args.limit else combos

    async def close(self) -> None:
        await self.composer.aclose()
        if self.gemini is not None:
            await self.gemini.aclose()

    async def each[I, R](self, items: Sequence[I], fn: Callable[[I], Awaitable[R]]) -> list[R]:
        """並行處理；離線模式的假回應有共用狀態，所以逐一處理。"""
        limit = asyncio.Semaphore(1 if self.offline else self.settings.gemini_concurrency)

        async def one(item: I) -> R:
            async with limit:
                return await fn(item)

        return await asyncio.gather(*(one(i) for i in items))

    async def request(self, brand: Brand, product: Product, template_id: TemplateId) -> SpecRequest:
        brief = await self.composer.sim_brief(brand, product, TEXT)
        hits = hits_of(brand)
        return SpecRequest(
            'job_experiment', 1, brand, product, brief, get_template(template_id), 'comfyui', 123456789,
            [h.chunk_id for h in hits], [],
            choose_visual_style(brand, brief.tone, None).style, text=TEXT, hits=hits,
        )  # fmt: skip

    async def default_spec(self, brand: Brand, product: Product, template_id: TemplateId) -> PromptSpec:
        return await self.composer.sim_prompt(await self.request(brand, product, template_id), flawed=False)

    # ---------- probe ----------

    async def probe(self) -> None:
        if self.args.offline:
            print('probe：離線模式略過')
            return
        client = genai.Client(api_key=self.settings.gemini_api_key.get_secret_value())
        model = await client.aio.models.get(model=self.settings.gemini_llm_model)
        print(f'模型 {model.name}：輸入上限 {model.input_token_limit:,}、輸出上限 {model.output_token_limit:,}')

        class Probe(BaseModel):
            answer: str
            numbers: list[int]

        response = await client.aio.models.generate_content(
            model=self.settings.gemini_llm_model,
            contents='用繁體中文回答：台灣最高的山是哪一座？並列出 3 個 1 到 10 的整數。',
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_json_schema=gemini_adapter.gemini_schema(Probe),
                seed=42,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        parsed = Probe.model_validate_json(response.text or '')
        print(f'結構化輸出：{parsed}')
        print(f'用量：{response.usage_metadata}')
        self.report.results['probe'] = {
            'model': model.name, 'parsed': parsed.model_dump(),
            'usage': response.usage_metadata.model_dump() if response.usage_metadata else None,
        }  # fmt: skip

    # ---------- spec ----------

    async def spec(self) -> None:
        jobs = [
            (brand, product, template_id)
            for brand, product, template_id in self.combos
            for _ in range(self.args.repeat)
        ]

        async def build(job: tuple[Brand, Product, TemplateId]) -> tuple[bool, list[str], list[str]]:
            brand, product, template_id = job
            request = await self.request(brand, product, template_id)
            if self.offline:
                self.offline.next_spec = await self.composer.sim_prompt(request, flawed=False)
            run = ExperimentRun()
            payload = await self._spec_payload(request)
            call = GeminiCall(
                kind='spec', model=self.settings.gemini_llm_model, system=load_prompt('spec'),
                parts=[json.dumps(payload, ensure_ascii=False, indent=1)], schema=SpecDraft,
                scope=UsageScope('job_experiment', brand.id, 1, template_id), seed=request.seed,
            )  # fmt: skip
            draft = await self.client.generate(call, run)
            _, issues = await self.composer.spec(draft, request)
            return run.format_retries() == 0, [i.code for i in issues if i.retry], [i.code for i in issues]

        results = await self.each(jobs, build)
        total = len(results)
        format_ok = sum(ok for ok, _, _ in results)
        guard_ok = sum(not retry for _, retry, _ in results)
        codes = Counter(code for _, _, all_codes in results for code in all_codes)
        self.report.results['spec'] = {
            'total': total, 'formatFirstTry': format_ok, 'guardFirstTry': guard_ok, 'issueCodes': dict(codes),
        }  # fmt: skip
        print(f'結構化輸出：格式第一次就通過 {format_ok}/{total}、不必重問就通過護欄 {guard_ok}/{total}')
        print(f'  護欄的問題：{dict(codes)}')

    async def _spec_payload(self, request: SpecRequest) -> dict[str, Any]:
        from app.pipeline.gemini import GeminiAgent

        agent = GeminiAgent(self.client, self.composer, self.settings)
        return await agent._spec_payload(request)

    # ---------- 審查共用 ----------

    async def poster(self, spec: PromptSpec, brand: Brand, product: Product, name: str) -> ComposedPoster:
        render = self.render(spec, brand, name)
        return await self.posters.compose('job_experiment', render, product, brand)

    def render(self, spec: PromptSpec, brand: Brand, name: str) -> Render:
        return Render(
            id=f'job_experiment_{name}', job_id='job_experiment', round=1, template_id=spec.template_id, variant=0,
            background=ProceduralBackground(kind='procedural', seed=1, palette=spec.palette, style=brand.id),
            spec=spec, score=None, passed=None, checks=[],
        )  # fmt: skip

    async def review(
        self, brand: Brand, spec: PromptSpec, poster: ComposedPoster, drawn: PromptSpec, label: str
    ) -> ReviewResult:
        """以 spec 的文案比對（預期），poster 是依 drawn 畫的海報（可能有刻意的錯字）。"""
        if self.offline:
            self.offline.next_spec = None
        reviewer = (
            OfflineReviewer(self.client, self.composer, self.settings, drawn_text(drawn, brand))
            if self.offline
            else GeminiReviewer(self.client, self.composer, self.settings)
        )
        return await reviewer.review(brand, self.render(spec, brand, label), 7, poster, ExperimentRun())

    # ---------- ocr ----------

    async def ocr(self) -> None:
        async def check(job: tuple[Brand, Product, TemplateId]) -> list[dict[str, Any]]:
            brand, product, template_id = job
            spec = await self.default_spec(brand, product, template_id)
            rows = []
            cases = (
                ('correct', spec),
                ('typo', with_first_char(spec, '某')),
                ('missing_glyph', with_first_char(spec, '这')),
            )
            for case, drawn in cases:
                poster = await self.poster(drawn, brand, product, f'{brand.id}_{template_id}_{case}')
                result = await self.review(brand, spec, poster, drawn, f'{brand.id}_{template_id}_{case}')
                ocr = next(c for c in result.checks if c.id == 'ocr_typo')
                rows.append(
                    {'brand': brand.id, 'template': template_id, 'case': case, 'status': ocr.status, 'value': ocr.value}
                )
            return rows

        rows = [row for rows in await self.each(self.combos, check) for row in rows]
        self.report.results['ocr'] = rows
        correct = [r for r in rows if r['case'] == 'correct']
        caught = [r for r in rows if r['case'] != 'correct']
        exact = sum(r['value'].startswith('0 處') for r in correct)
        noticed = sum(r['status'] != 'pass' for r in caught)
        boxes = sum(r['status'] == 'fail' for r in caught if r['case'] == 'missing_glyph')
        print(f'轉錄：正確海報 0 處差異 {exact}/{len(correct)}；錯字與方塊有差異 {noticed}/{len(caught)}')
        print(f'  方塊判定不通過 {boxes}/{len(correct)}')

    # ---------- vlm ----------

    async def vlm_cases(self, brand: Brand, product: Product) -> list[tuple[str, PromptSpec]]:
        spec = await self.default_spec(brand, product, 'ig-post')
        boxes = {b.id: b for b in spec.layout}
        headline = boxes['headline'].bbox
        logo = boxes['logo'].model_copy(
            update={'bbox': (headline[0] + 20, headline[1] + 10, boxes['logo'].bbox[2], boxes['logo'].bbox[3])}
        )
        occluded = spec.model_copy(update={'layout': [logo if b.id == 'logo' else b for b in spec.layout]})
        exaggerated = spec.model_copy(update={'copy_': spec.copy_.model_copy(update={'subhead': EXAGGERATED})})
        return [('correct', spec), ('occlusion', occluded), ('exaggeration', exaggerated)]

    async def vlm(self, repeats: int = 1, key: str = 'vlm') -> None:
        cases = [
            (brand, product, case, spec)
            for brand, product in self.brands
            for case, spec in await self.vlm_cases(brand, product)
        ]

        async def judge(item: tuple[Brand, Product, str, PromptSpec]) -> list[dict[str, Any]]:
            brand, product, case, spec = item
            poster = await self.poster(spec, brand, product, f'{brand.id}_vlm_{case}')
            rows = []
            for attempt in range(repeats):
                result = await self.review(brand, spec, poster, spec, f'{brand.id}_vlm_{case}_{attempt}')
                statuses: dict[str, str] = {c.id: c.status for c in result.checks if c.kind == 'vlm'}
                reasons = {c.id: c.value for c in result.checks if c.kind == 'vlm'}
                rows.append({'brand': brand.id, 'case': case, 'attempt': attempt, **statuses, 'values': reasons})
            return rows

        rows = [row for rows in await self.each(cases, judge) for row in rows]
        self.report.results[key] = rows
        if key == 'vlm':
            correct = [r for r in rows if r['case'] == 'correct']
            ok = sum(all(r[c] == 'pass' for c in VLM_CHECKS) for r in correct)
            occlusion = sum(r['vlm_occlusion'] != 'pass' for r in rows if r['case'] == 'occlusion')
            exaggeration = sum(r['vlm_exaggeration'] != 'pass' for r in rows if r['case'] == 'exaggeration')
            n = len(self.brands)
            print(f'VLM 判讀：正確海報三項通過 {ok}/{len(correct)}')
            print(f'  抓到遮擋 {occlusion}/{n}、抓到誇大 {exaggeration}/{n}')
        else:
            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for r in rows:
                groups.setdefault((r['brand'], r['case']), []).append(r)
            same = sum(all(r[c] == g[0][c] for r in g for c in VLM_CHECKS) for g in groups.values())
            print(f'穩定性：三次審查狀態一致 {same}/{len(groups)}')

    def summary(self) -> None:
        usage: dict[str, dict[str, Any]] = {}
        for kind in dict.fromkeys(r[1] for r in self.ledger.records):
            records = [r for r in self.ledger.records if r[1] == kind]
            seconds = [t['seconds'] for t in self.report.timings if t['kind'] == kind]
            n = len(records)
            avg = {
                'input': sum(r[3].input_tokens for r in records) / n,
                'cached': sum(r[3].cached_tokens for r in records) / n,
                'output': sum(r[3].output_tokens for r in records) / n,
                'thinking': sum(r[3].thinking_tokens for r in records) / n,
            }
            usage[kind] = {
                'responses': n,
                'calls': len(seconds),
                'avgInput': round(avg['input']),
                'avgCached': round(avg['cached']),
                'avgOutput': round(avg['output']),
                'avgThinking': round(avg['thinking']),
                'avgSeconds': round(sum(seconds) / len(seconds), 1) if seconds else None,
                'maxSeconds': max(seconds) if seconds else None,
                'cost': float(sum(r[4] for r in records)),
            }
            tokens = (
                f'輸入 {avg["input"]:,.0f}（快取 {avg["cached"]:,.0f}）'
                f'／輸出 {avg["output"]:,.0f}（思考 {avg["thinking"]:,.0f}）'
            )
            timing = f'平均 {usage[kind]["avgSeconds"]} 秒、最長 {usage[kind]["maxSeconds"]} 秒' if seconds else ''
            print(f'{kind}：{n} 個回應，{tokens} tokens；{timing}；US${usage[kind]["cost"]:.4f}')
        self.report.results['usage'] = usage
        print(f'合計 {len(self.ledger.records)} 個回應，US${self.ledger.total:.4f}')


class OfflineReviewer(GeminiReviewer):
    """離線模式：把預期的文字放進 payload，讓 OfflineClient 當作轉錄回傳。"""

    def __init__(self, client: LlmClient, composer: ComposerClient, settings: Settings, expected: list[str]) -> None:
        super().__init__(_Expecting(client, expected), composer, settings)


class _Expecting(LlmClient):
    def __init__(self, inner: LlmClient, expected: list[str]) -> None:
        self.inner = inner
        self.expected = expected

    async def generate[T: BaseModel](self, call: GeminiCall[T], run: Any) -> T:
        parts = [
            json.dumps({'expected': self.expected}, ensure_ascii=False) if isinstance(p, str) else p for p in call.parts
        ]
        return await self.inner.generate(
            GeminiCall(call.kind, call.model, call.system, parts, call.schema, call.scope, call.seed), run
        )


def api_key(args: argparse.Namespace) -> str:
    if args.offline:
        return ''
    key = os.environ.get('GEMINI_API_KEY') or (
        dotenv_values(args.env_file).get('GEMINI_API_KEY') if args.env_file.is_file() else None
    )
    if not key:
        sys.exit(f'沒有 GEMINI_API_KEY：請設定環境變數，或寫進 {args.env_file}')
    return key


async def main(args: argparse.Namespace) -> None:
    if args.thinking:
        level = types.ThinkingLevel.LOW if args.thinking == 'low' else types.ThinkingLevel.HIGH
        for kind in gemini_adapter.THINKING:
            gemini_adapter.THINKING[kind] = level
    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            image_mode='sim',
            agent_mode='gemini',
            gemini_api_key=api_key(args),
            data_dir=Path(tmp) / 'data',
        )
        experiment = Experiment(args, settings, report)
        try:
            steps = ['probe', 'spec', 'ocr', 'vlm', 'stability'] if args.step == 'all' else [args.step]
            for step in steps:
                if step == 'stability':
                    await experiment.vlm(repeats=3, key='stability')
                else:
                    await getattr(experiment, step)()
        except BudgetExceeded as error:
            # 已完成的步驟照樣寫進報告
            print(f'停止：{error.message}')
            report.results['stopped'] = error.message
        finally:
            experiment.summary()
            await experiment.close()
    out = REPO_ROOT / 'data' / 'experiments' / f'plan6b-{datetime.now():%Y%m%d-%H%M%S}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        'thinking': args.thinking,
        'limit': args.limit,
        'repeat': args.repeat,
        'budget': args.budget,
        'offline': args.offline,
    }
    out.write_text(
        json.dumps({'meta': meta, **report.results, 'timings': report.timings}, ensure_ascii=False, indent=1),
        encoding='utf-8',
    )
    print(f'報告：{out}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Plan 6B 規格 §2 的 Gemini 實驗')
    parser.add_argument('step', choices=['probe', 'spec', 'ocr', 'vlm', 'stability', 'all'])
    parser.add_argument('--thinking', choices=['low', 'high'])
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--budget', type=float, default=3.0)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--env-file', type=Path, default=REPO_ROOT / '.env')
    parser.add_argument('--composer', default='http://127.0.0.1:3900')
    asyncio.run(main(parser.parse_args()))
