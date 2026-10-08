"""讀取 contracts/fixtures/（由 web 的 `npm run fixtures` 產生）。"""

import json
from functools import cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'contracts' / 'fixtures'
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')


@cache
def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding='utf-8')


def load_fixture(name: str) -> Any:
    """每次回傳新的物件（測試可以放心修改）。"""
    return json.loads(_read(name))
