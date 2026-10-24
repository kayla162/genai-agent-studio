import type { Brand, Tone, VisualStyle } from '@/types/contract';

/** 任務使用的背景風格與寫進 log 的說明（與 backend/app/visual_style.py 一致） */
export interface ChosenStyle { style: VisualStyle; note: string }

/**
 * styleId 有值時使用該組（品牌沒有這一組時丟出錯誤）；
 * null 時取第一組 tones 含 tone 的風格，都沒有時用第一組。
 */
export function chooseVisualStyle(brand: Brand, tone: Tone, styleId: string | null): ChosenStyle {
  if (styleId !== null) {
    const style = brand.visualStyles.find((s) => s.id === styleId);
    if (!style) throw new Error(`品牌「${brand.name}」沒有這個背景風格：${styleId}`);
    return { style, note: `背景風格：${style.label}（指定）` };
  }
  const matched = brand.visualStyles.find((s) => s.tones.includes(tone));
  if (matched) return { style: matched, note: `背景風格：${matched.label}（自動：語氣 ${tone}）` };
  const first = brand.visualStyles[0];
  return { style: first, note: `背景風格：${first.label}（自動：沒有對應語氣 ${tone} 的風格，使用第一組）` };
}

/** 依 id 取得品牌的背景風格（id 已在建立任務時檢查過） */
export function styleById(brand: Brand, id: string): VisualStyle {
  const style = brand.visualStyles.find((s) => s.id === id);
  if (!style) throw new Error(`品牌「${brand.name}」沒有這個背景風格：${id}`);
  return style;
}
