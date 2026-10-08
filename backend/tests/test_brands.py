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
    loaded, errors = load_brands(tmp_path)
    assert [e.message for e in errors] == ['Logo 圖檔必須放在 brands/ 資料夾內：../x.png']
    b = loaded[0]
    assert b.brand.logo is not None
    assert b.brand.logo.url == '/files/brands/assets/logo.png'
    assert b.logo_path == tmp_path / 'assets' / 'logo.png'
    assert b.style_images == [tmp_path / 'assets' / 'mood.jpg']
    assert len(b.source_hash) == 64
