"""Gemini 結構化輸出、護欄結果與背景色系量測的型別：與 web/src/types/agent.ts、
web/src/lib/review/background.ts 一致（contracts/fixtures/agent.json）。"""

import json

import pytest
from pydantic import ValidationError

from app.adapters.gemini import gemini_schema
from app.pipeline.gemini_types import BriefDraft, GuardIssue, SpecDraft, VlmVerdict
from app.pipeline.ports import BackgroundPalette
from tests.fixtures import load_fixture


def test_parses_the_typescript_examples_without_changes() -> None:
    data = load_fixture('agent.json')
    draft = SpecDraft.model_validate(data['specDraft'])
    assert draft.to_json() == data['specDraft']
    verdict = VlmVerdict.model_validate(data['vlmVerdict'])
    assert verdict.to_json() == data['vlmVerdict']
    issues = [GuardIssue.model_validate(i) for i in data['guardIssues']]
    assert [i.to_json() for i in issues] == data['guardIssues']
    assert {i.code for i in issues} == {
        'emoji_removed',
        'missing_glyph',
        'banned_word',
        'too_long',
        'invented_offer',
        'empty_field',
        'product_glyph',
        'layout_invalid',
        'layout_rule',
        'text_too_small',
        'prompt_invalid',
    }


def test_parses_the_background_palette_examples_without_changes() -> None:
    examples = load_fixture('agent.json')['backgroundPalettes']
    parsed = [BackgroundPalette.model_validate(e) for e in examples]
    assert [p.to_json() for p in parsed] == examples
    assert [p.off_hex for p in parsed] == ['#3FD27A', None]


def test_the_spec_schema_has_no_references_and_eight_boxes() -> None:
    schema = gemini_schema(SpecDraft)
    text = json.dumps(schema)
    assert '$ref' not in text and '$defs' not in text and '"title"' not in text
    layout = schema['properties']['layout']
    assert (layout['minItems'], layout['maxItems']) == (8, 8)
    assert layout['items']['properties']['bbox']['minItems'] == 4
    assert schema['properties']['priceLabel']['type'] == 'string'


def test_brief_drafts_reject_unknown_tones() -> None:
    base = {
        'sellingPoints': ['5重玻尿酸'],
        'audience': '25–35 歲上班族',
        'tone': 'gentle',
        'campaign': None,
        'offer': None,
        'period': None,
        'style': [],
    }
    assert BriefDraft.model_validate(base).tone == 'gentle'
    with pytest.raises(ValidationError):
        BriefDraft.model_validate({**base, 'tone': 'sad'})
