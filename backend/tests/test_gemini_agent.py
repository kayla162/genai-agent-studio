"""GeminiAgent：需求拆解、Prompt 構建（composer 的 /spec 護欄、重問與退回）與 Query Rewriting 的護欄。

Gemini 用 FakeGemini（預先寫好的回應）；護欄用測試啟動的 composer（需要字型）。不需要資料庫。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.adapters.composer import ComposerClient, brand_json
from app.adapters.gemini import GeminiCall
from app.brands import load_brands
from app.contract import Brand, BrandRules, PromptSpec, RagChunk, RagHit, ReviewCheck
from app.pipeline.gemini import GeminiAgent, guard_brief
from app.pipeline.gemini_types import BriefDraft, FixDraft, RewriteDraft, SpecDraft
from app.pipeline.ports import PreviousRound, SpecRequest
from app.settings import Settings
from app.templates import get_template
from tests.fake_gemini import FakeGemini
from tests.fake_run import FakeRun
from tests.fixtures import BRANDS_DIR, load_fixture

LOADED = {b.brand.id: b for b in load_brands(BRANDS_DIR)[0]}
SELUNE = LOADED['selune'].brand
SERUM = LOADED['selune'].samples[0]
TEXT = '週年慶 2026/10/15–11/15 主打買一送一，溫柔療癒'
GOOD = SpecDraft.model_validate(load_fixture('agent.json')['specDraft'])
SETTINGS = Settings(_env_file=None, image_mode='sim', agent_mode='gemini')


def hit(chunk_id: str) -> RagHit:
    chunk = next(c for c in SELUNE.guideline_chunks if c.id == chunk_id)
    return RagHit(
        chunk_id=chunk.id, source=chunk.source, section=chunk.section, tag=chunk.tag, text=chunk.text, vector_score=0.9
    )


def check(id_: str, status: str = 'fail', value: str = '不通過', rag_ref: str | None = None) -> ReviewCheck:
    return ReviewCheck.model_validate(
        {
            'id': id_,
            'name': id_,
            'kind': 'rule',
            'rule': '規則',
            'value': value,
            'status': status,
            'target': None,
            'ragRef': rag_ref,
        }
    )


@pytest.fixture
async def composer(composer_url: str) -> AsyncIterator[ComposerClient]:
    client = ComposerClient(composer_url)
    yield client
    await client.aclose()


async def request(composer: ComposerClient, brand: Brand = SELUNE, **overrides: Any) -> SpecRequest:
    brief = await composer.sim_brief(brand, SERUM, TEXT)
    fields: dict[str, Any] = {
        'job_id': 'job_agent',
        'round': 1,
        'brand': brand,
        'product': SERUM,
        'brief': brief,
        'template': get_template('ig-post'),
        'engine': 'comfyui',
        'seed': 42,
        'rag_refs': ['selune#color', 'selune#law'],
        'fixes': [],
        'text': TEXT,
        'hits': [hit('selune#color'), hit('selune#law')],
        'previous': None,
        **overrides,
    }
    return SpecRequest(**fields)


def user_text(call: GeminiCall[Any]) -> str:
    return '\n'.join(p for p in call.parts if isinstance(p, str))


def guard_warnings(run: FakeRun) -> list[str]:
    return [m for m in run.messages('warn') if m.startswith('護欄：')]


# ---------- 需求拆解 ----------


def test_guard_brief_fills_in_what_the_program_decides() -> None:
    draft = BriefDraft(
        selling_points=[],
        audience='上班族',
        tone='gentle',
        campaign='週年慶',
        offer='買一送一',
        period='10/15–11/15',
        style=['Premium', 'soft light', '高級', 'premium', 'minimal'],
    )
    parsed = guard_brief(draft, '週年慶主打買一送一', SERUM)
    assert parsed.product_name == SERUM.name
    assert parsed.selling_points == SERUM.features[:3]
    assert parsed.period is None  # 需求沒有任何數字
    assert parsed.style == ['premium', 'minimal']
    assert guard_brief(draft, '10/15 開始', None).product_name is None
    assert guard_brief(draft, '10/15 開始', None).period == '10/15–11/15'


async def test_parse_brief_sends_the_brand_tones_and_the_product(composer: ComposerClient) -> None:
    draft = BriefDraft(
        selling_points=['神經醯胺'],
        audience='熬夜族',
        tone='science',
        campaign=None,
        offer=None,
        period=None,
        style=['clean'],
    )
    gemini = FakeGemini(brief=[draft])
    parsed = await GeminiAgent(gemini, composer, SETTINGS).parse_brief(SELUNE, '幫熬夜族做精華液海報', SERUM)
    assert parsed.model_dump(include={'tone', 'selling_points', 'product_name'}) == {
        'tone': 'science',
        'selling_points': ['神經醯胺'],
        'product_name': SERUM.name,
    }
    (call,) = gemini.calls
    assert (call.kind, call.scope.job_id, call.scope.brand_id, call.model) == (
        'brief',
        None,
        'selune',
        'gemini-3.8-flash',
    )
    text = user_text(call)
    for expected in ('幫熬夜族做精華液海報', '溫柔療癒', '專業科研', '活潑年輕', '簡約', '5重玻尿酸', SELUNE.category):
        assert expected in text


# ---------- Prompt 構建 ----------


async def test_a_compliant_draft_is_used_as_it_is(composer: ComposerClient) -> None:
    gemini = FakeGemini(spec=[GOOD])
    run = FakeRun('job_agent')
    req = await request(composer)
    spec = await GeminiAgent(gemini, composer, SETTINGS).build_spec(req, run)
    assert isinstance(spec, PromptSpec)
    assert list(spec.copy_.headline) == GOOD.headline
    assert spec.copy_.subhead == GOOD.subhead
    assert [list(b.bbox) for b in spec.layout] == [b.bbox for b in GOOD.layout]
    assert GOOD.scene in spec.positive_prompt
    (call,) = gemini.calls
    assert (call.kind, call.scope.job_id, call.scope.round, call.scope.target, call.seed) == (
        'spec',
        'job_agent',
        1,
        'ig-post',
        42,
    )
    text = user_text(call)
    assert hit('selune#color').text in text and hit('selune#law').text in text
    # 只放實際引用的切塊，不放品牌的其他規範
    assert next(c.text for c in SELUNE.guideline_chunks if c.id == 'selune#layout') not in text
    payload = json.loads(text)
    default_layout = await composer.layout('ig-post')
    assert payload['template']['defaultLayout'] == [{'id': b.id, 'bbox': list(b.bbox)} for b in default_layout]
    assert payload['brief'] == {'text': TEXT, 'parsed': req.brief.to_json()}
    assert guard_warnings(run) == []
    assert any(GOOD.rationale in m for m in run.messages('info'))


async def test_asks_again_with_the_guard_issues(composer: ComposerClient) -> None:
    flawed = GOOD.model_copy(update={'headline': ['这一夜修護', GOOD.headline[1]]})
    gemini = FakeGemini(spec=[flawed, GOOD])
    run = FakeRun('job_agent')
    spec = await GeminiAgent(gemini, composer, SETTINGS).build_spec(await request(composer), run)
    assert list(spec.copy_.headline) == GOOD.headline
    first, second = gemini.calls
    assert '这一夜修護' not in user_text(first)
    assert '標題第 1 行「这一夜修護」有伺服器字型沒有的字：「这」' in user_text(second)
    assert guard_warnings(run) == []


async def test_falls_back_to_the_defaults_after_the_second_try(composer: ComposerClient) -> None:
    broken_layout = [b.model_copy(update={'bbox': [0, 0, 10, 10]}) for b in GOOD.layout]
    flawed = GOOD.model_copy(update={'headline': ['这一夜修護', GOOD.headline[1]], 'layout': broken_layout})
    gemini = FakeGemini(spec=[flawed, flawed])
    run = FakeRun('job_agent')
    spec = await GeminiAgent(gemini, composer, SETTINGS).build_spec(await request(composer), run)
    assert spec.copy_.headline[0] == '一夜溫柔修護'
    assert spec.layout == await composer.layout('ig-post')
    warnings = guard_warnings(run)
    assert any(w.endswith('，已改用預設文案') and '这' in w for w in warnings)
    assert any(w.endswith('，已改用預設版型') for w in warnings)


async def test_the_next_round_sees_the_previous_round(composer: ComposerClient) -> None:
    first = await GeminiAgent(FakeGemini(spec=[GOOD]), composer, SETTINGS).build_spec(
        await request(composer), FakeRun()
    )
    previous = PreviousRound(
        spec=first,
        checks=[check('product_ratio', value='25.5%', rag_ref='selune#layout')],
        fixes=[],
    )
    gemini = FakeGemini(spec=[GOOD])
    await GeminiAgent(gemini, composer, SETTINGS).build_spec(
        await request(composer, round=2, previous=previous, fixes=['product_ratio']), FakeRun()
    )
    text = user_text(gemini.calls[0])
    assert '25.5%' in text and 'product_ratio' in text and first.copy_.subhead in text


async def test_layout_rules_reach_gemini_with_the_brand_numbers(composer: ComposerClient) -> None:
    strict = SELUNE.model_copy(
        update={'rules': BrandRules(max_delta_e=5, min_whitespace=0.3, product_ratio=(0.4, 0.6))}
    )
    gemini = FakeGemini(spec=[GOOD, GOOD])
    run = FakeRun('job_agent')
    await GeminiAgent(gemini, composer, SETTINGS).build_spec(await request(composer, brand=strict), run)
    assert '商品框佔畫面 25.5%，品牌規範為 40%–60%' in user_text(gemini.calls[1])
    assert any(w.endswith('，已改用預設版型') for w in guard_warnings(run))


# ---------- Query Rewriting ----------


async def test_rewrite_guard_keeps_failing_checks_fills_gaps_and_requeries(composer: ComposerClient) -> None:
    spec = await GeminiAgent(FakeGemini(spec=[GOOD]), composer, SETTINGS).build_spec(await request(composer), FakeRun())
    checks = [
        check('banned_words', rag_ref='selune#law'),
        check('color_delta', status='pass', rag_ref='selune#color'),
        check('product_ratio', value='18.0%', rag_ref='selune#layout'),
    ]
    draft = RewriteDraft(
        fixes=[
            FixDraft(check_id='banned_words', title='文案改寫', desc='把「根治」改成「改善外觀」'),
            FixDraft(check_id='banned_words', title='文案再改寫一次吧', desc='刪除「保證有效」'),
            FixDraft(check_id='color_delta', title='色彩修正', desc='已通過，不該出現'),
        ],
        requery=None,
    )
    gemini = FakeGemini(rewrite=[draft])
    run = FakeRun('job_agent')
    rewrite = await GeminiAgent(gemini, composer, SETTINGS).plan_rewrite(SELUNE, spec, checks, run, retries_left=2)
    assert [(f.check_id, f.title, f.desc) for f in rewrite.fixes] == [
        ('banned_words', '文案改寫', '把「根治」改成「改善外觀」；刪除「保證有效」'),
        ('product_ratio', '版面比例修正', '調整商品主體縮放，維持品牌規範的佔比與留白'),
    ]
    assert rewrite.query == '美妝保養 禁用詞 合規替代用語'
    (call,) = gemini.calls
    assert (call.kind, call.scope.target, call.scope.round) == ('rewrite', 'ig-post', 1)
    text = user_text(call)
    assert hit('selune#law').text in text and '18.0%' in text and '"retriesLeft": 2' in text


async def test_rewrite_keeps_the_gemini_requery(composer: ComposerClient) -> None:
    spec = await GeminiAgent(FakeGemini(spec=[GOOD]), composer, SETTINGS).build_spec(await request(composer), FakeRun())
    draft = RewriteDraft(
        fixes=[FixDraft(check_id='vlm_exaggeration', title='降低語氣', desc='改為使用者感受')],
        requery='保養品 誇大 用語 替代',
    )
    rewrite = await GeminiAgent(FakeGemini(rewrite=[draft]), composer, SETTINGS).plan_rewrite(
        SELUNE, spec, [check('vlm_exaggeration')], FakeRun(), retries_left=1
    )
    assert rewrite.query == '保養品 誇大 用語 替代'
    assert [f.title for f in rewrite.fixes] == ['降低語氣']


# ---------- 送給 composer 的品牌 ----------


def test_brand_json_keeps_only_the_first_chunk_of_each_tag() -> None:
    extra = [
        RagChunk(id='selune#upload-1', source='manual.pdf', section='§9', tag='law', text='很長的手冊'),
        RagChunk(id='selune#upload-2', source='manual.pdf', section='§10', tag='general', text='其他'),
    ]
    brand = SELUNE.model_copy(update={'guideline_chunks': [*SELUNE.guideline_chunks, *extra]})
    ids = [c['id'] for c in brand_json(brand)['guidelineChunks']]
    assert ids == [
        'selune#color',
        'selune#logo',
        'selune#law',
        'selune#layout',
        'selune#font',
        'selune#history',
        'selune#upload-2',
    ]
    assert brand_json(SELUNE) == {**SELUNE.to_json(), 'guidelineChunks': brand_json(SELUNE)['guidelineChunks']}
