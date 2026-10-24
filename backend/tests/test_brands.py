import shutil
from pathlib import Path

from app.brands import load_brands
from tests.fixtures import BRANDS_DIR, load_fixture


def test_demo_brands_match_the_frontend_data() -> None:
    loaded, errors = load_brands(BRANDS_DIR)
    assert errors == []
    fixture = load_fixture('brands.json')
    assert [b.brand.to_json() for b in loaded] == sorted(fixture['brands'], key=lambda b: b['id'])
    samples = [p.to_json() for b in loaded for p in b.samples]
    assert samples == sorted(fixture['products'], key=lambda p: p['brandId'])


def test_the_template_is_skipped_but_valid_once_copied(tmp_path: Path) -> None:
    assert '_template' not in [b.brand.id for b in load_brands(BRANDS_DIR)[0]]
    shutil.copy(BRANDS_DIR / '_template.yaml', tmp_path / 'my-brand.yaml')
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    brand = loaded[0].brand
    assert brand.id == 'my-brand'
    assert brand.logo is None
    alt = brand.guideline_chunks[-1]
    assert alt.model_dump() == {
        'id': 'my-brand#law-alt',
        'source': 'my-brand.yaml',
        'section': '合規替代用語對照',
        'tag': 'law',
        'text': '「根治」→「改善外觀」；「治療」→「保養」；「保證有效」→ 刪除。',
    }


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')


def test_reports_broken_files_and_keeps_loading_the_others(tmp_path: Path) -> None:
    shutil.copy(BRANDS_DIR / 'selune.yaml', tmp_path / 'selune.yaml')
    write(tmp_path / 'broken.yaml', 'id: [unclosed')
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    write(tmp_path / 'wrong-name.yaml', template)
    no_palette = template.replace('id: my-brand', 'id: no-palette').replace('palette:', 'colors:')
    write(tmp_path / 'no-palette.yaml', no_palette)
    no_logo = template.replace('id: my-brand', 'id: no-logo').replace('logo: null', 'logo: logo.png')
    write(tmp_path / 'no-logo.yaml', no_logo)
    loaded, errors = load_brands(tmp_path)
    assert [b.brand.id for b in loaded] == ['selune']
    messages = {e.file: e.message for e in errors}
    assert set(messages) == {'broken.yaml', 'wrong-name.yaml', 'no-palette.yaml', 'no-logo.yaml'}
    assert 'YAML' in messages['broken.yaml']
    assert messages['wrong-name.yaml'] == '檔名必須與 id 相同（id 為 my-brand）'
    assert 'palette' in messages['no-palette.yaml']
    assert messages['no-logo.yaml'] == 'Logo 圖檔不存在：logo.png'


def test_logo_and_style_images_resolve_inside_the_brands_folder(tmp_path: Path) -> None:
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'logo.png').write_bytes(b'\x89PNG')
    (tmp_path / 'assets' / 'mood.jpg').write_bytes(b'\xff\xd8')
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    text = template.replace('logo: null', 'logo: assets/logo.png')
    write(tmp_path / 'my-brand.yaml', text.replace('styleImages: []', 'styleImages: [assets/mood.jpg]'))
    escape = template.replace('id: my-brand', 'id: escape').replace('logo: null', 'logo: ../x.png')
    write(tmp_path / 'escape.yaml', escape)
    (tmp_path / 'assets' / 'logo.gif').write_bytes(b'GIF89a')
    gif_logo = template.replace('id: my-brand', 'id: gif-logo').replace('logo: null', 'logo: assets/logo.gif')
    write(tmp_path / 'gif-logo.yaml', gif_logo)
    loaded, errors = load_brands(tmp_path)
    assert [e.message for e in errors] == [
        'Logo 圖檔必須放在 brands/ 資料夾內：../x.png',
        'Logo 圖檔只支援 PNG、JPEG、WebP 與 SVG：assets/logo.gif',
    ]
    b = loaded[0]
    assert b.brand.logo is not None
    assert b.brand.logo.url == '/files/brands/assets/logo.png'
    assert b.logo_path == tmp_path / 'assets' / 'logo.png'
    assert b.style_images == [tmp_path / 'assets' / 'mood.jpg']
    assert len(b.source_hash) == 64


CASES = """caseStudies:
- {id: c1, title: 週年慶 IG 貼文, channel: IG 貼文, ctr: 4, notes: 柔光漸層}
- {id: c2, title: 夏季主圖, channel: 電商主圖, ctr: 3.5, notes: 水珠}"""


def test_case_studies_become_history_chunks_before_the_law_alt_chunk(tmp_path: Path) -> None:
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    write(tmp_path / 'my-brand.yaml', template.replace('caseStudies: []', CASES))
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    chunks = [c.model_dump() for c in loaded[0].brand.guideline_chunks]
    assert [c['id'] for c in chunks] == [
        'my-brand#color',
        'my-brand#logo',
        'my-brand#law',
        'my-brand#layout',
        'my-brand#case-1',
        'my-brand#case-2',
        'my-brand#law-alt',
    ]
    assert chunks[4:6] == [
        {
            'id': 'my-brand#case-1',
            'source': 'my-brand.yaml',
            'section': '週年慶 IG 貼文',
            'tag': 'history',
            'text': 'IG 貼文素材，CTR 4%：柔光漸層',
        },
        {
            'id': 'my-brand#case-2',
            'source': 'my-brand.yaml',
            'section': '夏季主圖',
            'tag': 'history',
            'text': '電商主圖素材，CTR 3.5%：水珠',
        },
    ]


def test_guideline_keys_cannot_take_the_generated_prefixes(tmp_path: Path) -> None:
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    write(tmp_path / 'my-brand.yaml', template.replace('{key: layout,', '{key: case-1,'))
    loaded, errors = load_brands(tmp_path)
    assert loaded == []
    assert [e.message for e in errors] == [
        'guidelines：Value error, key 不可以 doc-、hist-、case- 開頭（保留給上傳的手冊、歷史回寫與歷史案例）：case-1'
    ]


def test_the_source_hash_follows_the_converted_content(tmp_path: Path) -> None:
    """轉換規則改變（例如 Plan 5 加上歷史案例切塊）時，既有資料庫的品牌也會重新寫入切塊。"""
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    write(tmp_path / 'my-brand.yaml', template)
    before = load_brands(tmp_path)[0][0].source_hash
    write(tmp_path / 'my-brand.yaml', '# 只改註解\n' + template)
    assert load_brands(tmp_path)[0][0].source_hash == before
    write(tmp_path / 'my-brand.yaml', template.replace('caseStudies: []', CASES))
    assert load_brands(tmp_path)[0][0].source_hash != before


STYLES_START = 'visualStyles:\n'
TEMPLATE_STYLES = (
    "  - {id: daily, label: 日常, prompt: 'natural linen texture, soft morning light, warm minimal set', "
    'tones: [gentle, minimal]}\n'
    "  - {id: festive, label: 節慶, prompt: 'champagne gold confetti, satin ribbons, warm bokeh, celebratory set', "
    'tones: [playful]}\n'
)


def test_visual_styles_are_loaded_in_order_with_optional_tones(tmp_path: Path) -> None:
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')
    assert STYLES_START + TEMPLATE_STYLES in template
    plain = '  - {id: plain, label: 素面, prompt: plain wall}\n'
    write(tmp_path / 'my-brand.yaml', template.replace(TEMPLATE_STYLES, TEMPLATE_STYLES + plain))
    loaded, errors = load_brands(tmp_path)
    assert errors == []
    styles = loaded[0].brand.visual_styles
    assert [(s.id, s.label, s.tones) for s in styles] == [
        ('daily', '日常', ['gentle', 'minimal']),
        ('festive', '節慶', ['playful']),
        ('plain', '素面', []),
    ]
    assert styles[1].prompt == 'champagne gold confetti, satin ribbons, warm bokeh, celebratory set'


def test_visual_styles_are_validated(tmp_path: Path) -> None:
    template = (BRANDS_DIR / '_template.yaml').read_text(encoding='utf-8')

    def variant(name: str, styles: str) -> None:
        text = template.replace('id: my-brand', f'id: {name}').replace(STYLES_START + TEMPLATE_STYLES, styles)
        write(tmp_path / f'{name}.yaml', text)

    variant('old-field', 'visualStyle: warm minimal set\n')
    variant('duplicated', STYLES_START + TEMPLATE_STYLES + '  - {id: daily, label: 再一組, prompt: soft light}\n')
    variant('none', 'visualStyles: []\n')
    seven = ''.join(f'  - {{id: s{i}, label: 風格{i}, prompt: soft light}}\n' for i in range(7))
    variant('seven', STYLES_START + seven)
    variant('bad-id', STYLES_START + '  - {id: Daily Set, label: 日常, prompt: soft light}\n')
    variant('bad-tone', STYLES_START + '  - {id: daily, label: 日常, prompt: soft light, tones: [calm]}\n')
    loaded, errors = load_brands(tmp_path)
    assert loaded == []
    messages = {e.file: e.message for e in errors}
    assert 'visualStyle 已改為 visualStyles' in messages['old-field.yaml']
    assert messages['duplicated.yaml'] == 'visualStyles：Value error, 背景風格的 id 重複：daily'
    assert messages['none.yaml'].startswith('visualStyles：')
    assert messages['seven.yaml'].startswith('visualStyles：')
    assert messages['bad-id.yaml'].startswith('visualStyles.0.id：')
    assert messages['bad-tone.yaml'].startswith('visualStyles.0.tones.0：')
