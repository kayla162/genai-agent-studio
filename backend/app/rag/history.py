"""選定的海報 → 歷史回寫切塊：之後的任務檢索得到過去選定的海報。

web/src/lib/rag/history.ts 以相同的格式產生 mock 的切塊，修改時兩邊一起改（兩邊的測試比對同一段文字）。
"""

from datetime import tzinfo

from app.contract import HistoryEntry, RagChunk
from app.core.clock import parse_iso
from app.templates import get_template

#: 正向提示詞只取前面這麼多字（以 code point 計算），超過時加上「…」
PROMPT_CHARS = 120


def history_chunk(entry: HistoryEntry, product_name: str | None, tz: tzinfo) -> RagChunk:
    """id 為 {brandId}#hist-{historyId}（以 id upsert，重跑不會重複）；section 為「模板名稱・選定日期」，
    日期以 tz 計算。product_name 為回寫時的商品名稱，商品已刪除時為 None（文字省略商品名稱）。"""
    label = get_template(entry.template_id).label
    date = parse_iso(entry.selected_at).astimezone(tz).date().isoformat()
    return RagChunk(
        id=f'{entry.brand_id}#hist-{entry.id}',
        source=f'history/{entry.job_id}',
        section=f'{label}・{date}',
        tag='history',
        text=history_text(entry, label, product_name),
    )


def history_text(entry: HistoryEntry, label: str, product_name: str | None) -> str:
    """「商品名稱・模板海報」與審查分數、標題與副標、賣點、正向提示詞的前 120 字；空白的項目省略。

    商品名稱放在第一句的開頭：檢索的查詢字串以「品牌名｜商品名」開頭，同一個商品過去選定的海報較容易被召回。
    """
    copy, render = entry.copy_, entry.render
    poster = f'{product_name}・{label}海報' if product_name else f'{label}海報'
    review = '未經審查評分' if render.score is None else f'審查 {render.score} 分'
    prompt = render.spec.positive_prompt
    if len(prompt) > PROMPT_CHARS:
        prompt = prompt[:PROMPT_CHARS] + '…'
    fields = [
        ('標題', '／'.join(line for line in copy.headline if line)),
        ('副標', copy.subhead),
        ('賣點', '、'.join(copy.features)),
        ('正向提示詞', prompt),
    ]
    return '。'.join([f'{poster}，{review}', *(f'{name}：{value}' for name, value in fields if value)])
