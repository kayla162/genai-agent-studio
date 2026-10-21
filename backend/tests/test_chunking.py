"""切塊與前端（web/src/lib/rag/chunk.ts）的結果完全相同：contracts/fixtures/chunks.json。"""

from typing import Any

import pytest

from app.rag.chunking import EMBED_DIMS, chunk_document, embed_preview, guess_tag, tag_of
from tests.fixtures import load_fixture

DOCUMENTS: list[dict[str, Any]] = load_fixture('chunks.json')['documents']
PREVIEWS: list[dict[str, Any]] = load_fixture('chunks.json')['previews']


@pytest.mark.parametrize('doc', DOCUMENTS, ids=[f'{d["brandId"]}/{d["name"]}' for d in DOCUMENTS])
def test_chunks_match_the_frontend(doc: dict[str, Any]) -> None:
    brand_id, name, text = doc['brandId'], doc['name'], doc['text']
    max_chars = doc.get('maxChars')
    chunks = (
        chunk_document(brand_id, name, text)
        if max_chars is None
        else chunk_document(brand_id, name, text, max_chars=max_chars)
    )
    assert [c.to_json() for c in chunks] == doc['chunks']
    assert [embed_preview(c.text) for c in chunks] == doc['previews']


@pytest.mark.parametrize('case', PREVIEWS)
def test_embed_preview_matches_the_frontend(case: dict[str, Any]) -> None:
    values = embed_preview(case['text']) if 'n' not in case else embed_preview(case['text'], case['n'])
    assert values == case['values']


def test_the_fixture_covers_every_tag_and_a_rounding_tie() -> None:
    tags = {c['tag'] for d in DOCUMENTS for c in d['chunks']}
    assert tags == {'law', 'color', 'logo', 'font', 'layout', 'history', 'general'}
    assert any(d['chunks'] == [] for d in DOCUMENTS)
    assert any('maxChars' in d for d in DOCUMENTS)
    # -937.5 與 Math.round 一樣進位成 -937；Python 的 round() 取偶數會得 -938
    tie = next(p for p in PREVIEWS if p['text'] == '四捨五入丁愪狁')
    assert tie['values'][0] == -0.937
    assert round(-937.5) == -938


def test_splits_by_heading_and_paragraph_and_ends_bullets_with_a_full_stop() -> None:
    text = '# 色彩更新\n主色維持 #B76E79。\n\n# Logo 規範\n- Logo 淨空區至少 0.5 倍 Logo 高度\n- 深色背景使用反白 Logo'
    chunks = chunk_document('selune', 'ci_update.md', text)
    assert [(c.section, c.tag, c.text) for c in chunks] == [
        ('色彩更新', 'color', '主色維持 #B76E79。'),
        ('Logo 規範', 'logo', 'Logo 淨空區至少 0.5 倍 Logo 高度。深色背景使用反白 Logo。'),
    ]
    assert all(c.source == 'ci_update.md' for c in chunks)


def test_whitespace_follows_javascript() -> None:
    # JS 的 trim() 會去掉 U+FEFF，但 U+0085 不算空白（Python 的 str.strip() 剛好相反）
    assert chunk_document('selune', 'a.txt', '﻿開頭\u0085。')[0].text == '開頭\u0085。'
    # 漢字之間的換行拿掉，英文旁的保留
    assert chunk_document('selune', 'a.txt', '標題靠左\n對齊網格。\nLogo\n置於左上。')[0].text == (
        '標題靠左對齊網格。Logo 置於左上。'
    )


def test_hard_splits_long_sentences_by_code_point() -> None:
    chunks = chunk_document('selune', 'a.txt', '😀' * 20, max_chars=8)
    assert [len(c.text) for c in chunks] == [8, 8, 4]


def test_ids_are_stable_and_unique_per_document() -> None:
    text = '第一段。\n\n第二段。'
    a = chunk_document('selune', 'a.md', text)
    assert [c.id for c in a] == [c.id for c in chunk_document('selune', 'a.md', text)]
    assert len({c.id for c in a}) == 2
    assert a[0].id.startswith('selune#doc-') and a[0].id.endswith('-1')
    assert chunk_document('selune', 'b.md', text)[0].id != a[0].id


def test_returns_no_chunks_for_blank_text() -> None:
    assert chunk_document('selune', 'empty.txt', ' \n\n ') == []


def test_tags() -> None:
    assert guess_tag('禁止宣稱療效') == 'law'
    assert guess_tag('標題使用思源宋體字型') == 'font'
    assert guess_tag('商品主體置中，留白 40%') == 'layout'
    assert guess_tag('門市營業時間') == 'general'
    assert tag_of('字型規範', '標題最多兩行。') == 'font'
    assert tag_of('色彩', '標誌置於左上。') == 'logo'


def test_embed_preview_is_deterministic_and_bounded() -> None:
    v = embed_preview('品牌主色')
    assert v == embed_preview('品牌主色')
    assert len(v) == 6
    assert all(abs(x) <= 1 for x in v)
    assert embed_preview('另一段文字') != v
    assert EMBED_DIMS == 1024
