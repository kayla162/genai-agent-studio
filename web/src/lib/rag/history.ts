import type { HistoryEntry, RagChunk } from '@/types/contract';
import { getTemplate } from '@/lib/compose/templates';

/** 正向提示詞只取前面這麼多字（以 code point 計算），超過時加上「…」 */
export const PROMPT_CHARS = 120;

/** section 的日期以台灣時間計算（與後端 TIMEZONE 的預設值相同） */
const DATE = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' });

function localDate(iso: string): string {
  const parts = Object.fromEntries(DATE.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/**
 * 「商品名稱・模板海報」與審查分數、標題與副標、賣點、正向提示詞的前 120 字；空白的項目省略。
 * 商品名稱放在第一句的開頭：檢索的查詢字串以「品牌名｜商品名」開頭，同一個商品過去選定的海報較容易被召回。
 */
function historyText(entry: HistoryEntry, label: string, productName: string | null): string {
  const { copy, render } = entry;
  const poster = productName ? `${productName}・${label}海報` : `${label}海報`;
  const review = render.score === null ? '未經審查評分' : `審查 ${render.score} 分`;
  const chars = [...render.spec.positivePrompt];
  const prompt = chars.length > PROMPT_CHARS ? `${chars.slice(0, PROMPT_CHARS).join('')}…` : chars.join('');
  const fields: [string, string][] = [
    ['標題', copy.headline.filter(Boolean).join('／')],
    ['副標', copy.subhead],
    ['賣點', copy.features.join('、')],
    ['正向提示詞', prompt],
  ];
  return [`${poster}，${review}`, ...fields.filter(([, value]) => value).map(([name, value]) => `${name}：${value}`)].join('。');
}

/**
 * 選定的海報 → 歷史回寫切塊（mock 的 selectRender 加進知識庫）：之後的任務檢索得到過去選定的海報。
 * 與後端 backend/app/rag/history.py 的格式相同，修改時兩邊一起改（兩邊的測試比對同一段文字）。
 * productName 為回寫時的商品名稱，商品已刪除時為 null（文字省略商品名稱）。
 */
export function historyChunk(entry: HistoryEntry, productName: string | null): RagChunk {
  const label = getTemplate(entry.templateId).label;
  return {
    id: `${entry.brandId}#hist-${entry.id}`,
    source: `history/${entry.jobId}`,
    section: `${label}・${localDate(entry.selectedAt)}`,
    tag: 'history',
    text: historyText(entry, label, productName),
  };
}
