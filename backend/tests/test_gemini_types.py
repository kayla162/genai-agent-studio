"""Gemini 結構化輸出與護欄結果的型別：與 web/src/types/agent.ts 一致（contracts/fixtures/agent.json）。"""

import json

import pytest
from pydantic import ValidationError

from app.adapters.gemini import gemini_schema
from app.pipeline.gemini_types import BriefDraft, GuardIssue, SpecDraft, VlmVerdict
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
