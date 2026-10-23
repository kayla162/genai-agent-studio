"""Pydantic 驗證錯誤的中文說明（API 的 400 與 Gemini 的格式錯誤共用）。"""

from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.contract import JobInput
from app.validation import describe_error, describe_errors


class Box(BaseModel):
    bbox: list[int] = Field(min_length=4, max_length=4)


class Sample(BaseModel):
    tone: Literal['gentle', 'science', 'playful', 'minimal']
    boxes: list[Box]
    count: int = Field(ge=1)
    name: str = Field(max_length=4)

    @field_validator('name')
    @classmethod
    def no_spaces(cls, value: str) -> str:
        if ' ' in value:
            raise ValueError('名稱不能有空白')
        return value


def errors_of(data: object) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        Sample.model_validate(data)
    return [describe_error(e) for e in caught.value.errors()]


def test_describes_common_errors_in_chinese() -> None:
    assert errors_of({'tone': 'sad', 'boxes': [{'bbox': [1, 2, 3]}], 'count': 0, 'name': 'ab cd'}) == [
        'tone：必須是 gentle、science、playful、minimal 其中之一',
        'boxes.0.bbox：長度至少要 4（目前 3）',
        'count：必須 ≥ 1',
        'name：最多 4 個字',
    ]
    assert errors_of({'boxes': [{'bbox': [1, 2, 3, 4, 5]}], 'count': 'x', 'name': 'a b'}) == [
        'tone：缺少欄位',
        'boxes.0.bbox：長度最多 4（目前 5）',
        'count：必須是整數',
        'name：名稱不能有空白',
    ]


def test_describes_json_and_type_errors() -> None:
    with pytest.raises(ValidationError) as caught:
        Sample.model_validate_json('{"tone": "gentle", "boxes": ')
    assert describe_error(caught.value.errors()[0]).startswith('不是合法的 JSON')
    assert errors_of({'tone': 'gentle', 'boxes': 'x', 'count': 1, 'name': 'a'}) == ['boxes：必須是陣列']


def test_drops_the_request_body_prefix_and_joins_several_errors() -> None:
    with pytest.raises(ValidationError) as caught:
        JobInput.model_validate({})
    errors = caught.value.errors()
    body = [{**errors[0], 'loc': ('body', *errors[0]['loc'])}]
    assert describe_errors(body) == f'{".".join(str(p) for p in errors[0]["loc"])}：缺少欄位'
    assert describe_errors(errors, limit=2).count('；') == 1
    assert describe_errors(errors, limit=2).endswith(f'（共 {len(errors)} 個問題）')


def test_keeps_unknown_error_types_as_they_are() -> None:
    error = {'type': 'something_new', 'loc': ('a',), 'msg': 'Something new happened', 'input': None}
    assert describe_error(error) == 'a：Something new happened'
