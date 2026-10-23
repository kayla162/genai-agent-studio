import type { LayoutElementId, ReviewCheck } from '@/types/contract';
import { ELEMENT_LABELS } from '@/lib/compose/layout';
import type { PosterScene, TextOp } from '@/lib/compose/scene';
import { truncate } from '@/lib/core/text';

/**
 * OCR 錯字比對：海報上實際繪製的每一段文字，與 VLM 轉錄的文字比對。
 * VLM 不知道預期的文案（避免照抄），所以這裡在轉錄全文中為每段文字找最接近的子字串，編輯距離的總和就是差異數。
 */

/** 換算到送出給 VLM 的圖片後，字級小於這個值（像素）的段落不比對（實驗決定） */
export const OCR_MIN_PX = 14;
/** 差異數不超過這個值時為 warn（VLM 可能讀錯一個字），超過為 fail（實驗決定） */
export const OCR_WARN_MAX = 1;
/** VLM 以這個字表示畫面上的方塊或無法辨識的符號 */
export const BOX = '□';
/** 說明文字中每段文字最多顯示的字數 */
const SHOWN_CHARS = 12;

/** 海報上的一段文字（scene.ts 的 TextOp） */
export interface OcrSegment { el: LayoutElementId; text: string; size: number }
export interface OcrDiff { el: LayoutElementId; expected: string; read: string; distance: number }
export interface OcrResult {
  /** 比對到的差異總數（編輯距離的總和） */
  diffs: number;
  /** 轉錄含方塊：畫面有字型沒有的字 */
  boxes: boolean;
  /** 差異最多的元素中，差異最多的一段；沒有差異時為 null */
  worst: OcrDiff | null;
  /** 比對的段落數 */
  compared: number;
  /** 字級太小而略過的段落數 */
  skipped: number;
}

const seg = (op: TextOp): OcrSegment => ({ el: op.el, text: op.text, size: op.size });

/** 海報實際繪製的文字（含徽章、價格的「NT$」、原價、按鈕）；畫 Logo 圖檔時沒有向量字標 */
export function expectedSegments(scene: PosterScene): OcrSegment[] {
  const out: OcrSegment[] = [];
  for (const op of scene.ops) {
    if (op.kind === 'text') out.push(seg(op));
    else if (op.kind === 'badge') out.push(...op.texts.map(seg));
    else if (op.kind === 'logo' && op.image === null && op.wordmark) out.push(seg(op.wordmark));
  }
  return out.filter((s) => s.text.trim() !== '');
}

/** NFKC、英文轉小寫，移除空白、標點與符號（方塊與「?」保留：它們代表畫面上讀不出來的字） */
export function normalizeOcr(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, (ch) => (ch === BOX || ch === '?' ? ch : ''));
}

/** semi-global alignment：needle 全部比對，haystack 可以從任何位置開始與結束；回傳最小的編輯距離與對到的子字串 */
export function bestMatch(needle: string, haystack: string): { distance: number; read: string } {
  const a = [...needle];
  const b = [...haystack];
  // prev[j]／cur[j]：needle 前 i 個字對齊到 haystack 第 j 個字之前結束的最小距離；start 記錄對齊的起點
  let prev = Array.from({ length: b.length + 1 }, () => 0);
  let prevStart = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    const curStart = [0];
    for (let j = 1; j <= b.length; j++) {
      const sub = prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1);
      const del = prev[j] + 1;
      const ins = cur[j - 1] + 1;
      const best = Math.min(sub, del, ins);
      cur.push(best);
      curStart.push(best === sub ? prevStart[j - 1] : best === del ? prevStart[j] : curStart[j - 1]);
    }
    prev = cur;
    prevStart = curStart;
  }
  let end = 0;
  for (let j = 1; j <= b.length; j++) if (prev[j] < prev[end]) end = j;
  return { distance: prev[end], read: b.slice(prevStart[end], end).join('') };
}

/**
 * 比對轉錄（lines，依閱讀順序）與海報上的文字。scale 為送出圖片與畫布的比例，
 * 換算後字級小於 minPx 的段落不比對（VLM 看不清楚，不能算錯字）。
 */
export function ocrDiffs(lines: string[], segments: OcrSegment[], scale: number, minPx = OCR_MIN_PX): OcrResult {
  const haystack = normalizeOcr(lines.join(''));
  const byElement = new Map<LayoutElementId, { total: number; worst: OcrDiff }>();
  let diffs = 0;
  let compared = 0;
  let skipped = 0;
  for (const s of segments) {
    if (s.size * scale < minPx) {
      skipped++;
      continue;
    }
    const needle = normalizeOcr(s.text);
    if (needle === '') continue;
    compared++;
    const { distance, read } = bestMatch(needle, haystack);
    if (distance === 0) continue;
    diffs += distance;
    const diff: OcrDiff = { el: s.el, expected: s.text, read, distance };
    const entry = byElement.get(s.el);
    if (!entry) byElement.set(s.el, { total: distance, worst: diff });
    else {
      entry.total += distance;
      if (distance > entry.worst.distance) entry.worst = diff;
    }
  }
  let worst: OcrDiff | null = null;
  let most = 0;
  for (const { total, worst: diff } of byElement.values()) {
    if (total > most) {
      most = total;
      worst = diff;
    }
  }
  return { diffs, boxes: haystack.includes(BOX), worst, compared, skipped };
}

/** ocr_typo 檢查的說明、狀態與目標；沒有轉錄（模擬模式）時與 6A 相同：0 處差異、通過、標題 */
export function ocrCheck(result?: OcrResult): Pick<ReviewCheck, 'value' | 'status' | 'target'> {
  if (!result) return { value: '0 處差異', status: 'pass', target: 'headline' };
  const { diffs, boxes, worst } = result;
  const parts: string[] = [];
  if (worst) {
    const shown = `${ELEMENT_LABELS[worst.el]}「${truncate(worst.expected, SHOWN_CHARS)}」`;
    const what = worst.read ? `${shown}讀成「${truncate(worst.read, SHOWN_CHARS)}」` : `${shown}沒有讀到`;
    parts.push(`${diffs} 處差異（${what}）`);
  } else if (!boxes) parts.push('0 處差異');
  if (boxes) parts.push('畫面有無法顯示的字（方塊）');
  return {
    value: parts.join('・'),
    status: boxes || diffs > OCR_WARN_MAX ? 'fail' : diffs > 0 ? 'warn' : 'pass',
    target: worst?.el ?? (boxes ? 'canvas' : 'headline'),
  };
}
