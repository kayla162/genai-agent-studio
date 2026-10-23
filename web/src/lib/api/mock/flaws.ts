import type { Brand, Palette, PromptSpec } from '@/types/contract';
import { setParam } from '@/lib/agent/prompt';
import { deltaEHex } from '@/lib/review/color';

export const FLAWS = ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer'] as const;
export type Flaw = (typeof FLAWS)[number];

interface FlawData {
  offPalette: Palette;
  /** 含禁用詞的副標；品牌沒有禁用詞時為 null（不製造這個失誤） */
  bannedSubhead: string | null;
}

export const FLAW_DATA: Record<string, FlawData> = {
  selune: {
    offPalette: { primary: '#E0458A', secondary: '#FFE3EF', accent: '#F49AC1', ink: '#3B1F2E' },
    bannedSubhead: '7天根治暗沉・醫療級修護',
  },
  'misty-isle': {
    offPalette: { primary: '#1E88E5', secondary: '#E3F2FD', accent: '#90CAF9', ink: '#0D2238' },
    bannedSubhead: '保證提神・治療疲勞',
  },
};

/** 示範品牌用固定的失誤；其他品牌（使用者自己的設定檔）由品牌的主色與禁用詞推算 */
export function flawData(brand: Pick<Brand, 'id' | 'palette' | 'bannedWords'>): FlawData {
  const known = FLAW_DATA[brand.id];
  if (known) return known;
  // 兩組示範偏色中，與品牌主色差最多的一組，確保主色色差檢查會未通過
  const [a, b] = [FLAW_DATA.selune.offPalette, FLAW_DATA['misty-isle'].offPalette];
  const primary = brand.palette.primary;
  const offPalette = deltaEHex(a.primary, primary) >= deltaEHex(b.primary, primary) ? a : b;
  return { offPalette, bannedSubhead: brand.bannedWords.length ? brand.bannedWords.slice(0, 2).join('・') : null };
}

/** 模擬第一輪 LLM／生圖常見的失誤，讓審查與 Query Rewriting 有東西可以修 */
export function applyFlaws(spec: PromptSpec, flaws: readonly Flaw[], brand: Pick<Brand, 'id' | 'palette' | 'bannedWords'>): PromptSpec {
  const data = flawData(brand);
  const out = structuredClone(spec);

  if (flaws.includes('offPalette')) {
    out.palette = { ...data.offPalette };
    out.positivePrompt = `${out.positivePrompt}, vivid saturated colors`;
    out.injection = setParam(out.injection, 'positive_prompt', out.positivePrompt);
  }
  if (flaws.includes('bannedCopy') && data.bannedSubhead) {
    out.copy.subhead = data.bannedSubhead;
  }
  if (flaws.includes('logoCrowding')) {
    const logo = out.layout.find((b) => b.id === 'logo')!;
    const head = out.layout.find((b) => b.id === 'headline')!;
    logo.bbox[1] = head.bbox[1] - Math.round(logo.bbox[3] * 0.55);
  }
  if (flaws.includes('missingDisclaimer')) {
    const parts = out.copy.disclaimer.split('｜').filter((p) => !p.startsWith('*'));
    out.copy.disclaimer = parts.length ? parts.join('｜') : '圖片僅供參考';
  }
  return out;
}
