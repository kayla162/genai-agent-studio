"""GeminiReviewer：讀審查用海報、呼叫 VLM（FakeGemini）、以 composer 的 /review 比對轉錄並產生 11 項檢查。

使用測試啟動的 composer（需要字型）繪製審查用海報；不需要資料庫。
"""

import io
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from google.genai import types
from PIL import Image

from app.adapters.composer import ComposerClient
from app.adapters.gemini import GeminiError
from app.contract import Brand, Product, PromptSpec, Render, ReviewCheck
from app.errors import AppError, BudgetExceeded
from app.pipeline import gemini
from app.pipeline.gemini import GeminiReviewer
from app.pipeline.gemini_types import VlmVerdict
from app.pipeline.ports import BackgroundPalette, ComposedPoster, ReviewResult
from app.pipeline.review import ComposerPosters
from app.settings import Settings
from tests.fake_gemini import FakeGemini
from tests.fake_run import FakeRun
from tests.fixtures import load_fixture

TIMELINE = load_fixture('timelines/selune-retry.json')
JOB_ID: str = TIMELINE['jobId']
CLEAN = next(
    Render.model_validate(r)
    for item in TIMELINE['events']
    if item['event']['type'] == 'render.completed'
    for r in item['event']['renders']
    if r['id'] == f'{JOB_ID}_r2_ig-post_v0'
)
CATALOG = load_fixture('brands.json')
SELUNE = Brand.model_validate(next(b for b in CATALOG['brands'] if b['id'] == 'selune'))
SERUM = Product.model_validate(next(p for p in CATALOG['products'] if p['id'] == 'prod_selune_serum'))


def drawn_text(spec: PromptSpec) -> list[str]:
    """海報上畫出的文字（與 web 的 composePoster 相同的段落；順序不影響比對）。"""
    c = spec.copy_
    return [
        'SÉLUNE',
        *c.headline,
        c.subhead,
        *c.features,
        c.badge.top,
        c.badge.main,
        c.badge.sub,
        f'{c.product_name}｜{c.price.label}',
        'NT$',
        f'{c.price.sale:,}',
        f'原價 NT${c.price.original:,}',
        c.disclaimer,
    ]


def verdict(lines: list[str]) -> VlmVerdict:
    return VlmVerdict.model_validate(
        {
            'lines': lines,
            'exaggeration': {'status': 'pass', 'phrases': [], 'reason': ''},
            'occlusion': {'status': 'pass', 'elements': [], 'reason': ''},
            'quality': {'status': 'pass', 'issues': [], 'reason': ''},
        }
    )


class RecordingComposer(ComposerClient):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url)
        self.reviews: list[dict[str, Any]] = []

    async def review(
        self,
        spec: PromptSpec,
        brand: Brand,
        measured_primary: str | None,
        vlm: VlmVerdict | None = None,
        vlm_scale: float = 1.0,
        background: BackgroundPalette | None = None,
    ) -> ReviewResult:
        self.reviews.append({'vlm': vlm, 'vlm_scale': vlm_scale, 'background': background})
        return await super().review(spec, brand, measured_primary, vlm, vlm_scale, background)


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[RecordingComposer]:
    client = RecordingComposer(composer_url)
    yield client
    await client.aclose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, agent_mode='gemini', data_dir=tmp_path / 'data', brands_dir=tmp_path / 'brands')


@pytest.fixture
async def poster(composer: RecordingComposer, settings: Settings) -> ComposedPoster:
    return await ComposerPosters(composer, settings).compose(JOB_ID, CLEAN, SERUM, SELUNE)


def by_id(checks: list[ReviewCheck], id_: str) -> ReviewCheck:
    return next(c for c in checks if c.id == id_)


async def review(
    composer: ComposerClient, settings: Settings, poster: ComposedPoster, fake: FakeGemini
) -> ReviewResult:
    return await GeminiReviewer(fake, composer, settings).review(SELUNE, CLEAN, 7, poster, FakeRun(JOB_ID))


async def test_a_correct_transcription_passes_with_gemini_wording(
    composer: RecordingComposer, settings: Settings, poster: ComposedPoster
) -> None:
    fake = FakeGemini(vlm=[verdict(drawn_text(CLEAN.spec))])
    result = await review(composer, settings, poster, fake)
    assert len(result.checks) == 11
    assert by_id(result.checks, 'ocr_typo').value == '0 處差異'
    # 背景色系依審查用海報的背景量測判定（程式產生的背景在品牌色系內），不是模擬
    assert poster.background is not None
    assert composer.reviews[-1]['background'] == poster.background
    assert by_id(result.checks, 'bg_palette').status == 'pass'
    assert by_id(result.checks, 'bg_palette').value.startswith('色系外 ')
    vlm = [c for c in result.checks if c.kind == 'vlm']
    assert [c.value for c in vlm] == ['未發現誇大用語', '無重疊遮擋', '構圖與畫質良好']
    assert result.passed
    (call,) = fake.calls
    assert (call.kind, call.model, call.scope.job_id, call.scope.round, call.scope.target) == (
        'vlm',
        'gemini-3.8-flash',
        JOB_ID,
        CLEAN.round,
        CLEAN.id,
    )
    image = next(p for p in call.parts if isinstance(p, types.Part))
    assert image.inline_data is not None and image.inline_data.mime_type == 'image/png'
    assert Path(settings.data_dir / 'jobs' / JOB_ID / f'{CLEAN.id}.png').read_bytes() == image.inline_data.data
    payload = json.loads(next(p for p in call.parts if isinstance(p, str)))
    assert payload['image'] == {'width': 1440, 'height': 1800}
    assert payload['layout'][0] == {'id': 'logo', 'name': 'Logo', 'box': list(CLEAN.spec.layout[0].bbox)}
    assert payload['brand']['bannedWords'] == SELUNE.banned_words
    # 不提供預期文案：VLM 要讀畫面上實際的字
    for text in (*CLEAN.spec.copy_.headline, CLEAN.spec.copy_.subhead):
        assert text not in json.dumps(payload, ensure_ascii=False)
    assert composer.reviews[-1]['vlm_scale'] == 1.0


async def test_misread_and_missing_glyphs_show_up_in_ocr_typo(
    composer: RecordingComposer, settings: Settings, poster: ComposedPoster
) -> None:
    lines = drawn_text(CLEAN.spec)
    line = CLEAN.spec.copy_.headline[1]
    typo = [f'某{line[1:]}' if t == line else t for t in lines]
    result = await review(composer, settings, poster, FakeGemini(vlm=[verdict(typo)]))
    assert by_id(result.checks, 'ocr_typo').status == 'warn'
    boxed = await review(composer, settings, poster, FakeGemini(vlm=[verdict([*lines, '□'])]))
    assert by_id(boxed.checks, 'ocr_typo').status == 'fail'
    assert not boxed.passed


async def test_a_smaller_image_scales_the_boxes_and_the_ocr_threshold(
    composer: RecordingComposer, settings: Settings, poster: ComposedPoster, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gemini, 'VLM_MAX_SIDE', 900)
    fake = FakeGemini(vlm=[verdict(drawn_text(CLEAN.spec))])
    await review(composer, settings, poster, fake)
    (call,) = fake.calls
    image = next(p for p in call.parts if isinstance(p, types.Part))
    assert image.inline_data is not None and image.inline_data.data is not None
    with Image.open(io.BytesIO(image.inline_data.data)) as img:
        assert img.size == (720, 900)
    payload = json.loads(next(p for p in call.parts if isinstance(p, str)))
    assert payload['image'] == {'width': 720, 'height': 900}
    x, y, w, h = CLEAN.spec.layout[0].bbox
    assert payload['layout'][0]['box'] == [round(x / 2), round(y / 2), round(w / 2), round(h / 2)]
    assert composer.reviews[-1]['vlm_scale'] == 0.5


async def test_gemini_failures_fail_the_review_but_budgets_pass_through(
    composer: RecordingComposer, settings: Settings, poster: ComposedPoster
) -> None:
    unavailable = GeminiError('Gemini 暫時無法使用（HTTP 503），已重試 3 次')
    with pytest.raises(AppError, match=f'^Gemini 無法審查海報：{unavailable.message}$'):
        await review(composer, settings, poster, FakeGemini(vlm=[unavailable]))
    over = BudgetExceeded('本月 Gemini 費用已達上限（US$20.00）')
    with pytest.raises(BudgetExceeded):
        await review(composer, settings, poster, FakeGemini(vlm=[over]))
    with pytest.raises(AppError, match='審查需要伺服器端繪製的審查用海報'):
        await GeminiReviewer(FakeGemini(), composer, settings).review(SELUNE, CLEAN, 7, None, FakeRun(JOB_ID))
