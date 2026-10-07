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

export interface InlineDiff { prefix: string; removed: string; added: string; suffix: string }

/** 兩段文字只標出中間改變的部分（共同的前綴與後綴原樣保留）；注入參數對照使用 */
export function inlineDiff(a: string, b: string): InlineDiff {
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let s = 0;
  while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
  return { prefix: a.slice(0, p), removed: a.slice(p, a.length - s), added: b.slice(p, b.length - s), suffix: a.slice(a.length - s) };
}
