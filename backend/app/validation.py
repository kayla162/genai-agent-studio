"""Pydantic 驗證錯誤的中文說明：API 的 400 回應與 Gemini 回應的格式錯誤共用。

位置為 JSON 欄位路徑（去掉開頭的 body）；沒有對應的錯誤類型保留 Pydantic 的原文。
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

#: Pydantic 的 literal_error、enum 在 ctx.expected 列出可用的值（例如 "'a', 'b' or 'c'"）
QUOTED = re.compile(r"'([^']*)'")


def _choices(expected: Any) -> str:
    names = QUOTED.findall(str(expected))
    if len(names) > 1:
        return f'必須是 {"、".join(names)} 其中之一'
    return f'必須是 {names[0] if names else expected}'


def _message(error: Mapping[str, Any]) -> str:
    kind = error['type']
    ctx: Mapping[str, Any] = error.get('ctx') or {}
    match kind:
        case 'missing':
            return '缺少欄位'
        case 'literal_error' | 'enum':
            return _choices(ctx.get('expected', ''))
        case 'too_short':
            return f'長度至少要 {ctx.get("min_length")}（目前 {ctx.get("actual_length")}）'
        case 'too_long':
            return f'長度最多 {ctx.get("max_length")}（目前 {ctx.get("actual_length")}）'
        case 'string_too_short':
            return f'至少 {ctx.get("min_length")} 個字'
        case 'string_too_long':
            return f'最多 {ctx.get("max_length")} 個字'
        case 'greater_than_equal':
            return f'必須 ≥ {ctx.get("ge")}'
        case 'greater_than':
            return f'必須 > {ctx.get("gt")}'
        case 'less_than_equal':
            return f'必須 ≤ {ctx.get("le")}'
        case 'less_than':
            return f'必須 < {ctx.get("lt")}'
        case 'string_type':
            return '必須是字串'
        case 'int_type' | 'int_parsing' | 'int_from_float':
            return '必須是整數'
        case 'float_type' | 'float_parsing':
            return '必須是數字'
        case 'bool_type' | 'bool_parsing':
            return '必須是 true 或 false'
        case 'list_type' | 'tuple_type':
            return '必須是陣列'
        case 'dict_type' | 'model_type' | 'model_attributes_type':
            return '必須是物件'
        case 'json_invalid':
            return f'不是合法的 JSON（{ctx.get("error", "")}）'
        case 'extra_forbidden':
            return '不允許的欄位'
        case 'string_pattern_mismatch':
            return '格式不符'
        case 'value_error' | 'assertion_error':
            return str(error['msg']).removeprefix('Value error, ').removeprefix('Assertion failed, ')
        case _:
            return str(error['msg'])


def describe_error(error: Mapping[str, Any]) -> str:
    """「templateIds.0：必須是 ecom-main、scene、ig-post、story、banner 其中之一」"""
    loc = [str(part) for part in error['loc']]
    if loc and loc[0] == 'body':
        loc = loc[1:]
    location = '.'.join(loc)
    message = _message(error)
    return f'{location}：{message}' if location else message


def describe_errors(errors: Sequence[Mapping[str, Any]], limit: int = 5) -> str:
    """最多 limit 個問題，以「；」相連；超過時加上總數。"""
    shown = '；'.join(describe_error(e) for e in errors[:limit])
    return shown if len(errors) <= limit else f'{shown}（共 {len(errors)} 個問題）'
