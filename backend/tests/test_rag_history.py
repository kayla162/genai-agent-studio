"""歷史回寫切塊。web/src/lib/rag/history.test.ts 以同一筆歷史紀錄比對同一段文字（mock 的知識庫與後端一致）。"""

from zoneinfo import ZoneInfo

from app.contract import HistoryEntry, RagChunk
from app.rag.history import history_chunk
from tests.fixtures import selected_history

TAIPEI = ZoneInfo('Asia/Taipei')
#: selected_history 的商品（prod_selune_serum）
PRODUCT = '極光玻尿酸修護精華 30ml'

#: 與 web/src/lib/rag/history.test.ts 的 TEXT 相同
TEXT = (
    '極光玻尿酸修護精華 30ml・IG 貼文海報，審查 99 分。標題：一夜溫柔修護／醒來透亮發光。'
    '副標：7天感受透亮光采・專業修護配方*。賣點：5重玻尿酸、神經醯胺、無香精。'
    '正向提示詞：4:5 commercial photography backdrop, empty styled set with a single display surface, '
    'serene luxury skincare, crescent mo…'
)


def edited(entry: HistoryEntry, *, score: int | None, prompt: str, **copy: object) -> HistoryEntry:
    spec = entry.render.spec.model_copy(update={'positive_prompt': prompt})
    render = entry.render.model_copy(update={'score': score, 'spec': spec})
    return entry.model_copy(update={'render': render, 'copy_': entry.copy_.model_copy(update=copy)})


def test_builds_the_chunk_from_the_selected_poster() -> None:
    assert history_chunk(selected_history(), PRODUCT, TAIPEI) == RagChunk(
        id='selune#hist-hist_3fa2c1d0e9b8',
        source='history/job_20261007_1000_a1b2',
        # 2026-10-21T16:30Z 是台灣時間 10 月 22 日 00:30
        section='IG 貼文・2026-10-22',
        tag='history',
        text=TEXT,
    )


def test_the_section_date_follows_the_time_zone() -> None:
    assert history_chunk(selected_history(), PRODUCT, ZoneInfo('UTC')).section == 'IG 貼文・2026-10-21'


def test_leaves_out_the_product_name_when_the_product_was_deleted() -> None:
    assert history_chunk(selected_history(), None, TAIPEI).text == TEXT.removeprefix(f'{PRODUCT}・')


def test_leaves_out_empty_fields_and_cuts_the_prompt_at_120_characters() -> None:
    entry = selected_history().model_copy(update={'template_id': 'story'})
    bare = edited(entry, score=None, prompt='a' * 120, headline=('只有一行', ''), subhead='', features=[])
    expected = f'商品・限時動態海報，未經審查評分。標題：只有一行。正向提示詞：{"a" * 120}'
    assert history_chunk(bare, '商品', TAIPEI).text == expected
    # 以 code point 計算（與 TypeScript 相同，不是 UTF-16）：第 121 個字起省略
    long = edited(entry, score=80, prompt='𠀀' * 121, headline=('', ''), subhead='副標', features=['A'])
    expected = f'限時動態海報，審查 80 分。副標：副標。賣點：A。正向提示詞：{"𠀀" * 120}…'
    assert history_chunk(long, None, TAIPEI).text == expected
