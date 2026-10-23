// 海報字型的涵蓋表：Gemini 寫的文案若有伺服器字型沒有的字，海報會畫成方塊，所以護欄與品牌設定檔檢查都用這份表。
// 只給 composer（護欄、/glyphs）使用；不要被前端頁面匯入，以免把涵蓋表放進瀏覽器的 bundle。
import table from './glyphs.json';

/** 兩個海報字型（Noto Sans TC、Noto Serif TC）都涵蓋的字元，`[開始, 結束]`（含）依序排列；由 npm run glyphs 產生 */
export const GLYPH_RANGES: readonly (readonly [number, number])[] = table.ranges as [number, number][];

/** 字元是否在涵蓋表內（二分搜尋） */
export function hasGlyph(codePoint: number): boolean {
  let lo = 0;
  let hi = GLYPH_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [start, end] = GLYPH_RANGES[mid];
    if (codePoint < start) hi = mid - 1;
    else if (codePoint > end) lo = mid + 1;
    else return true;
  }
  return false;
}

/** 文字中伺服器字型沒有的字（空白除外），依出現順序、不重複 */
export function missingGlyphs(text: string): string[] {
  const missing: string[] = [];
  for (const ch of text) {
    if (/\s/u.test(ch) || missing.includes(ch)) continue;
    if (!hasGlyph(ch.codePointAt(0) ?? 0)) missing.push(ch);
  }
  return missing;
}

/**
 * emoji 與相關的組合字元：Extended_Pictographic、變體選擇符、ZWJ、keycap、膚色修飾符、區域指示符號（國旗）與 tag 字元。
 * 單獨的數字與 # * 不算 emoji（keycap 只移除組合用的符號，留下數字）。
 */
const EMOJI = /[\p{Extended_Pictographic}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{1F3FB}-\u{1F3FF}\u{1F1E6}-\u{1F1FF}\u{E0020}-\u{E007F}]/gu;

/** 移除 emoji 與裝飾用的組合字元；移除後留下的連續空白合併成一個，並去除前後空白 */
export function stripEmoji(text: string): string {
  const stripped = text.replace(EMOJI, '');
  return stripped === text ? text : stripped.replace(/[ 　]{2,}/g, ' ').trim();
}
