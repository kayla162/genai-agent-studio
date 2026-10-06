import type { LayoutElementId, PromptSpec } from '@/types/contract';

export interface SpecDiff { path: string; before: string; after: string }

const fmtBox = (spec: PromptSpec, id: LayoutElementId) => {
  const b = spec.layout.find((x) => x.id === id);
  return b ? `[${b.bbox.join(', ')}]` : '(無)';
};

/** 兩版 Prompt 之間，重試紀錄要顯示的欄位差異（固定順序） */
export function diffSpecs(a: PromptSpec, b: PromptSpec): SpecDiff[] {
  const rows: [path: string, before: string, after: string][] = [
    ['palette.primary', a.palette.primary, b.palette.primary],
    ['palette.secondary', a.palette.secondary, b.palette.secondary],
    ['layout[logo].bbox', fmtBox(a, 'logo'), fmtBox(b, 'logo')],
    ['copy.headline', a.copy.headline.join(' / '), b.copy.headline.join(' / ')],
    ['copy.subhead', a.copy.subhead, b.copy.subhead],
    ['copy.features', a.copy.features.join('、'), b.copy.features.join('、')],
    ['copy.disclaimer', a.copy.disclaimer, b.copy.disclaimer],
    ['negativePrompt', a.negativePrompt, b.negativePrompt],
  ];
  return rows.filter(([, x, y]) => x !== y).map(([path, before, after]) => ({ path, before, after }));
}
