"""讀取 contracts/fixtures/（由 web 的 `npm run fixtures` 產生），以及 tests/data/ 的測試檔案。"""

import atexit
import json
import shutil
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

from app.contract import HistoryEntry

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / 'contracts' / 'fixtures'
#: repo 追蹤的示範品牌檔（brands/ 裡其他檔案是使用者自己的品牌，不屬於測試的前提）
DEMO_BRAND_FILES = ('_template.yaml', 'selune.yaml', 'misty-isle.yaml')
TIMELINES = ('selune-retry', 'selune-needs-review', 'misty-first-pass')
#: 含中文文字層的兩頁 PDF（Chromium 以微軟正黑體輸出，文字層的部分漢字記成康熙部首）
SAMPLE_PDF = Path(__file__).parent / 'data' / 'ci-sample.pdf'


def _copy_demo_brands() -> Path:
    """只把示範品牌檔複製到暫存資料夾，測試不讀 repo 的 brands/：
    使用者在那裡加了自己的品牌（例如 my-brand-01.yaml）時，「剛好兩個示範品牌」的斷言才不會失敗。
    資料夾在每次 pytest 執行時建立一次，程式結束時刪除。"""
    root = Path(tempfile.mkdtemp(prefix='genai-test-brands-'))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    source = REPO_ROOT / 'brands'
    for name in DEMO_BRAND_FILES:
        shutil.copy(source / name, root / name)
    if (source / 'assets').is_dir():
        shutil.copytree(source / 'assets', root / 'assets')
    return root


BRANDS_DIR = _copy_demo_brands()


@cache
def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding='utf-8')


def load_fixture(name: str) -> Any:
    """每次回傳新的物件（測試可以放心修改）。"""
    return json.loads(_read(name))


def selected_history() -> HistoryEntry:
    """選定 selune-retry 任務的 IG 貼文最佳候選（第 2 輪 v0，審查 99 分）。
    web/src/lib/rag/history.test.ts 以同一筆歷史紀錄比對同一段回寫文字。"""
    data = load_fixture('timelines/selune-retry.json')
    events = [x['event'] for x in data['events']]
    best = next(e['bestRenderIds']['ig-post'] for e in events if e['type'] == 'job.completed')
    render = next(r for e in events if e['type'] == 'render.completed' for r in e['renders'] if r['id'] == best)
    return HistoryEntry.model_validate(
        {
            'id': 'hist_3fa2c1d0e9b8',
            'jobId': data['jobId'],
            'brandId': 'selune',
            'productId': data['input']['productId'],
            'input': data['input'],
            'templateId': 'ig-post',
            'render': {**render, 'score': 99, 'passed': True},
            'copy': render['spec']['copy'],
            'selectedAt': '2026-10-21T16:30:00.000Z',
            'favorite': False,
            'writtenToRag': False,
        }
    )
