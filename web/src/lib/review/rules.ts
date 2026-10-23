import type { Brand, Copy, LayoutElementId, PromptSpec, RagTag, ReviewCheck } from '@/types/contract';
import { boxMap } from '@/lib/compose/layout';
import { areaRatio, verticalGap } from '@/lib/core/geometry';
import { clamp, round1 } from '@/lib/core/num';
import { deltaEHex } from './color';
import { PRIMARY_MEASURE } from './measure';
import { ocrCheck, type OcrResult } from './ocr';

export function findBannedWords(texts: string[], banned: string[]): string[] {
  const joined = texts.join('\n');
  return banned.filter((w) => w !== '' && joined.includes(w));
}

export function hasClaim(texts: string[], claimWords: string[]): boolean {
  const joined = texts.join('\n');
  return claimWords.some((w) => joined.includes(w));
}

export function ragRefFor(brand: Brand, tag: RagTag): string | null {
  return brand.guidelineChunks.find((c) => c.tag === tag && !c.id.endsWith('-alt'))?.id ?? null;
}

/** 依版面元素拆出海報上的所有文字，讓禁用詞檢查能指出出現在哪個區塊 */
export function copyTexts(spec: PromptSpec): { id: LayoutElementId; text: string }[] {
  const c = spec.copy;
  return [
    { id: 'headline', text: c.headline.join('') },
    { id: 'subhead', text: c.subhead },
    { id: 'features', text: c.features.join('、') },
    { id: 'badge', text: [c.badge.top, c.badge.main, c.badge.sub].join('｜') },
    { id: 'price', text: `${c.price.label}｜${c.productName}` },
    { id: 'disclaimer', text: c.disclaimer },
  ];
}

/** 視為行銷宣稱的文案範圍（不含商品名稱與價格）；Prompt 構建與審查共用，確保兩邊判斷一致 */
export function claimTexts(copy: Pick<Copy, 'headline' | 'subhead' | 'features' | 'badge'>): string[] {
  return [copy.headline.join(''), copy.subhead, copy.features.join('、'), [copy.badge.top, copy.badge.main].join('｜')];
}

/** 文案中出現的禁用詞（依詞庫順序），以及第一個含禁用詞的版面區塊；禁用詞檢查與 VLM 誇大用語共用 */
export function bannedWordHits(spec: PromptSpec, brand: Brand): { words: string[]; target: LayoutElementId | null } {
  const texts = copyTexts(spec);
  const words = findBannedWords(texts.map((t) => t.text), brand.bannedWords);
  return { words, target: texts.find((t) => words.some((w) => t.text.includes(w)))?.id ?? null };
}

/** 量測範圍內沒有佔比夠大的彩色時，主色檢查的說明 */
export const NO_PRIMARY_MESSAGE = `未偵測到主色（主色區塊 < ${PRIMARY_MEASURE.minShare * 100}%）`;

/** 主色檢查說明中量到的顏色：`ΔE 0.3 · 偵測主色 #B76F7A`（hex 為大寫） */
const MEASURED_PRIMARY_LABEL = '偵測主色';
const MEASURED_PRIMARY_PATTERN = new RegExp(`${MEASURED_PRIMARY_LABEL} (#[0-9A-F]{6})$`);

/** 主色檢查（color_delta）說明文字裡量到的主色（#RRGGBB）；其他檢查或量不到主色時為 null。審查面板依此畫出色塊。 */
export function measuredPrimaryOf(check: Pick<ReviewCheck, 'id' | 'value'>): string | null {
  return check.id === 'color_delta' ? (MEASURED_PRIMARY_PATTERN.exec(check.value)?.[1] ?? null) : null;
}

export interface RuleContext {
  brand: Brand;
  spec: PromptSpec;
  /** 從海報量到的主色（measurePrimary）；量不到時為 null，主色檢查判定不通過 */
  measuredPrimary: string | null;
  /** VLM 轉錄與海報文字的比對結果（ocrDiffs）；沒有轉錄時（模擬模式）為 0 處差異 */
  ocr?: OcrResult;
}

/**
 * 版面的三項規則：Logo 淨空區、商品主體佔比、留白比例。審查（runRuleChecks）與 Prompt 構建的護欄（finalizeSpec）
 * 共用這個函式，兩邊的判斷才會一致。
 */
export function layoutRuleChecks(spec: PromptSpec, brand: Brand): ReviewCheck[] {
  const B = boxMap(spec.layout);
  const { width: W, height: H } = spec.canvas;
  const pct = (v: number) => `${round1(v * 100)}%`;

  const gap = verticalGap(B.logo, B.headline);
  const need = Math.round(B.logo.h * 0.5);

  const prod = areaRatio(B.product, W, H);
  const [lo, hi] = brand.rules.productRatio;
  const whitespace = 1 - Object.values(B).reduce((s, r) => s + areaRatio(r, W, H), 0);

  return [
    {
      id: 'logo_clearance', name: 'Logo 淨空區', kind: 'rule', rule: `間距 ≥ 0.5 × Logo 高（${need}px）`,
      value: gap < 0 ? `與標題重疊 ${-gap}px` : `間距 ${gap}px`,
      status: gap >= need ? 'pass' : 'fail', target: 'logo', ragRef: ragRefFor(brand, 'logo'),
    },
    {
      id: 'product_ratio', name: '商品主體佔比', kind: 'rule', rule: `${round1(lo * 100)}% – ${round1(hi * 100)}%`,
      value: pct(prod), status: prod >= lo && prod <= hi ? 'pass' : 'fail', target: 'product', ragRef: ragRefFor(brand, 'layout'),
    },
    {
      id: 'whitespace', name: '留白比例', kind: 'rule', rule: `≥ ${round1(brand.rules.minWhitespace * 100)}%`,
      value: pct(whitespace), status: whitespace >= brand.rules.minWhitespace ? 'pass' : 'fail', target: null,
      ragRef: ragRefFor(brand, 'layout'),
    },
  ];
}

export function runRuleChecks({ brand, spec, measuredPrimary, ocr }: RuleContext): ReviewCheck[] {
  const { words: banned, target: bannedTarget } = bannedWordHits(spec, brand);

  const color = measuredPrimary === null
    ? null
    : { hex: measuredPrimary.toUpperCase(), dE: deltaEHex(measuredPrimary, brand.palette.primary) };

  const claim = hasClaim(claimTexts(spec.copy), brand.claimWords);
  const hasNote = brand.disclaimerPhrase !== '' && spec.copy.disclaimer.includes(brand.disclaimerPhrase);

  const [logoClearance, productRatio, whitespace] = layoutRuleChecks(spec, brand);

  return [
    {
      id: 'banned_words', name: '禁用詞檢查', kind: 'rule', rule: '品牌禁用詞庫與法規用語',
      value: banned.length ? `禁用詞${banned.map((w) => `「${w}」`).join('')}` : '未偵測到禁用詞',
      status: banned.length ? 'fail' : 'pass', target: bannedTarget, ragRef: ragRefFor(brand, 'law'),
    },
    {
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: `ΔE2000 ≤ ${brand.rules.maxDeltaE}`,
      value: color ? `ΔE ${round1(color.dE)} · ${MEASURED_PRIMARY_LABEL} ${color.hex}` : NO_PRIMARY_MESSAGE,
      status: color && color.dE <= brand.rules.maxDeltaE ? 'pass' : 'fail', target: 'canvas', ragRef: ragRefFor(brand, 'color'),
    },
    logoClearance,
    {
      id: 'disclaimer', name: '效果宣稱註記', kind: 'rule',
      rule: brand.disclaimerPhrase ? `效果宣稱需加註「${brand.disclaimerPhrase}」` : '效果宣稱需加註說明',
      value: !claim ? '無效果宣稱' : hasNote ? '已加註' : '含效果宣稱但缺少註記',
      status: !claim || hasNote ? 'pass' : 'warn', target: 'disclaimer', ragRef: ragRefFor(brand, 'law'),
    },
    productRatio,
    whitespace,
    {
      id: 'ocr_typo', name: 'OCR 錯字比對', kind: 'rule', rule: '渲染文字與文案逐字比對', ...ocrCheck(ocr), ragRef: null,
    },
  ];
}

export function scoreChecks(checks: ReviewCheck[], jitter = 0): { score: number; passed: boolean } {
  const fails = checks.filter((c) => c.status === 'fail').length;
  const warns = checks.filter((c) => c.status === 'warn').length;
  return { score: clamp(Math.round(100 - fails * 14 - warns * 6 - jitter), 0, 100), passed: fails === 0 };
}
