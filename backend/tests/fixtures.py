"""讀取 contracts/fixtures/（由 web 的 `npm run fixtures` 產生），以及 tests/data/ 的測試檔案。"""

import json
from functools import cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / 'contracts' / 'fixtures'
BRANDS_DIR = REPO_ROOT / 'brands'
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')
#: 含中文文字層的兩頁 PDF（Chromium 以微軟正黑體輸出，文字層的部分漢字記成康熙部首）
SAMPLE_PDF = Path(__file__).parent / 'data' / 'ci-sample.pdf'


@cache
def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding='utf-8')


def load_fixture(name: str) -> Any:
    """每次回傳新的物件（測試可以放心修改）。"""
    return json.loads(_read(name))
