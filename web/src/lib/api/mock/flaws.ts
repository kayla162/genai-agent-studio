import type { Palette, PromptSpec } from '@/types/contract';
import { setParam } from '@/lib/agent/prompt';

export const FLAWS = ['offPalette', 'bannedCopy', 'logoCrowding', 'missingDisclaimer'] as const;
export type Flaw = (typeof FLAWS)[number];

export const FLAW_DATA: Record<string, { offPalette: Palette; bannedSubhead: string }> = {
  selune: {
    offPalette: { primary: '#E0458A', secondary: '#FFE3EF', accent: '#F49AC1', ink: '#3B1F2E' },
    bannedSubhead: '7天根治暗沉・醫療級修護',
  },
  'misty-isle': {
    offPalette: { primary: '#1E88E5', secondary: '#E3F2FD', accent: '#90CAF9', ink: '#0D2238' },
    bannedSubhead: '保證提神・治療疲勞',
  },
};

/** 模擬第一輪 LLM／生圖常見的失誤，讓審查與 Query Rewriting 有東西可以修 */
export function applyFlaws(spec: PromptSpec, flaws: readonly Flaw[]): PromptSpec {
  const data = FLAW_DATA[spec.brandId];
  if (!data) throw new Error(`No flaw data for brand: ${spec.brandId}`);
  const out = structuredClone(spec);

  if (flaws.includes('offPalette')) {
    out.palette = { ...data.offPalette };
    out.positivePrompt = `${out.positivePrompt}, vivid saturated colors`;
    out.injection = setParam(out.injection, 'positive_prompt', out.positivePrompt);
  }
  if (flaws.includes('bannedCopy')) {
    out.copy.subhead = data.bannedSubhead;
  }
  if (flaws.includes('logoCrowding')) {
    const logo = out.layout.find((b) => b.id === 'logo')!;
    const head = out.layout.find((b) => b.id === 'headline')!;
    logo.bbox[1] = head.bbox[1] - Math.round(logo.bbox[3] * 0.55);
    out.injection = setParam(out.injection, 'layout_boxes', JSON.stringify(out.layout.map((b) => [b.id, ...b.bbox])));
  }
  if (flaws.includes('missingDisclaimer')) {
    const parts = out.copy.disclaimer.split('｜').filter((p) => !p.startsWith('*'));
    out.copy.disclaimer = parts.length ? parts.join('｜') : '圖片僅供參考';
  }
  return out;
}
