// Prompt 構建的程式護欄（AGENT_MODE=gemini，composer 的 POST /spec）：Gemini 寫的文案、版面與場景，
// 由程式保證合規、畫得出來並符合品牌版面規則。與審查共用同一套文案與幾何函式，判斷結果才會一致。
import {
  LAYOUT_ELEMENT_IDS,
  type BBox, type Brand, type CheckId, type Copy, type Engine, type LayoutBox, type LayoutElementId, type ParsedBrief,
  type Product, type PromptSpec, type TemplateId,
} from '@/types/contract';
import type { GuardCode, GuardIssue, SpecDraft } from '@/types/agent';
import { missingGlyphs, stripEmoji } from '@/lib/compose/glyphs';
import { computeLayout, ELEMENT_LABELS } from '@/lib/compose/layout';
import { composePoster, type TextOp } from '@/lib/compose/scene';
import { getTemplate } from '@/lib/compose/templates';
import { intersectionArea, isInside, toRect } from '@/lib/core/geometry';
import { round1 } from '@/lib/core/num';
import { visLen } from '@/lib/core/text';
import { findBannedWords, layoutRuleChecks } from '@/lib/review/rules';
import { applyReplacements, buildCopy, buildDisclaimer, buildInjection, negativePromptOf, positivePromptOf } from './prompt';

/** 文案長度上限（視覺寬度，與 visLen 相同：中文 1、英數 0.58）；徽章英文以字元數計 */
export const LIMITS = { headline: 8, subhead: 22, feature: 12, badgeTop: 6, badgeMain: 6, priceLabel: 8, badgeSub: 16 } as const;
/** 最小字級（畫布短邊的比例，實驗決定）：標題與其他文字；徽章英文是裝飾，不檢查 */
export const TEXT_MIN = { headline: 0.04, other: 0.01 } as const;

/** POST /spec 的 request：後端 SpecRequest 的 JSON（品牌已精簡切塊） */
export interface GuardRequest {
  jobId: string;
  round: number;
  brand: Brand;
  product: Product;
  brief: ParsedBrief;
  /** 使用者的一句話需求（判斷文案中的價格與優惠是否出自需求） */
  text: string;
  templateId: TemplateId;
  engine: Engine;
  seed: number;
  ragRefs: string[];
  /** 之前各輪未通過的檢查（加強負向提示詞） */
  fixes: CheckId[];
}

/** 文案中的價格或優惠：折扣、買幾送幾、金額、百分比 */
const OFFER_TERMS = [
  /\d+(?:\.\d+)?\s*折/g,
  /[一二兩三四五六七八九十]+折/g,
  /買\s*[一二兩三四五六七八九十\d]+\s*送\s*[一二兩三四五六七八九十\d]+/g,
  /(?:NT\$|NTD|\$)\s*\d[\d,]*/gi,
  /\d[\d,]*\s*元/g,
  /\d+(?:\.\d+)?\s*[%％]/g,
  /BUY\s*\d+\s*GET\s*\d+/gi,
];
const squeeze = (s: string) => s.replace(/\s+/g, '').toUpperCase();
/** 只能是可列印的 ASCII（生圖提示詞要用英文） */
const ENGLISH = /^[\x20-\x7E]*$/;
const BADGE_SUB = /^[A-Z0-9 ]*$/;

class Issues {
  readonly list: GuardIssue[] = [];

  add(code: GuardCode, field: string, message: string, retry: boolean) {
    if (!this.list.some((i) => i.code === code && i.field === field)) this.list.push({ code, field, message, retry });
  }

  /** field 是否有需要重問的問題（有的話改用預設值） */
  failed(field: string): boolean {
    return this.list.some((i) => i.retry && i.field === field);
  }
}

interface TextRule {
  field: string;
  label: string;
  limit: number;
  required?: boolean;
}

/** 需求裡沒有提到的價格或優惠 */
function inventedOffers(text: string, req: GuardRequest): string[] {
  const allowed = squeeze([req.text, req.brief.offer ?? '', req.brief.period ?? ''].join(' '));
  const terms = OFFER_TERMS.flatMap((re) => [...text.matchAll(re)].map((m) => m[0]));
  return [...new Set(terms)].filter((t) => !allowed.includes(squeeze(t)) && !(/^BUY/i.test(t) && req.brief.offer));
}

/** Gemini 寫的一段文案：替代用語 → 移除 emoji → 去除空白 → 檢查空白、長度、禁用詞、缺字與新增的優惠 */
function cleanText(raw: string, rule: TextRule, req: GuardRequest, issues: Issues): string {
  const { field, label } = rule;
  const replaced = applyReplacements(raw, req.brand.replacements);
  const stripped = stripEmoji(replaced);
  if (stripped !== replaced) {
    const removed = [...replaced].filter((ch) => !stripped.includes(ch) && ch.trim() !== '').join('');
    issues.add('emoji_removed', field, `${label}有 emoji 或裝飾符號：「${removed}」`, false);
  }
  const text = stripped.trim();
  if (text === '') {
    if (rule.required) issues.add('empty_field', field, `${label}是空白的，請填寫`, true);
    return text;
  }
  if (visLen(text) > rule.limit) {
    issues.add('too_long', field, `${label}「${text}」太長（${round1(visLen(text))} 字），上限 ${rule.limit} 字`, true);
  }
  const banned = findBannedWords([text], req.brand.bannedWords);
  if (banned.length) {
    issues.add('banned_word', field, `${label}「${text}」有禁用詞：${banned.map((w) => `「${w}」`).join('')}，請改寫`, true);
  }
  const missing = missingGlyphs(text);
  if (missing.length) {
    issues.add('missing_glyph', field, `${label}「${text}」有伺服器字型沒有的字：「${missing.join('')}」，請改用繁體字或其他寫法`, true);
  }
  const offers = inventedOffers(text, req);
  if (offers.length) {
    issues.add('invented_offer', field, `${label}「${text}」提到需求裡沒有的價格或優惠：${offers.map((o) => `「${o}」`).join('')}，請移除`, true);
  }
  return text;
}

/** 徽章英文：轉大寫後只能有大寫英文、數字與空白 */
function cleanBadgeSub(raw: string, req: GuardRequest, issues: Issues): string {
  const field = 'badge.sub';
  const stripped = stripEmoji(raw);
  if (stripped !== raw) issues.add('emoji_removed', field, `徽章英文有 emoji 或裝飾符號：「${raw}」`, false);
  const text = stripped.trim().toUpperCase();
  if (text.length > LIMITS.badgeSub || !BADGE_SUB.test(text)) {
    issues.add('too_long', field, `徽章英文「${text}」只能用大寫英文、數字與空白，最多 ${LIMITS.badgeSub} 字元`, true);
  }
  const offers = inventedOffers(text, req);
  if (offers.length) {
    issues.add('invented_offer', field, `徽章英文「${text}」提到需求裡沒有的優惠：${offers.map((o) => `「${o}」`).join('')}，請移除`, true);
  }
  return text;
}

function guardCopy(draft: SpecDraft, req: GuardRequest, issues: Issues): Copy {
  const { brand, product, brief } = req;
  const fallback = buildCopy(brand, product, brief, true);
  const pick = <T>(field: string, value: T, def: T) => (issues.failed(field) ? def : value);

  const headline = draft.headline.map((line, i) => {
    const field = `headline.${i}`;
    const text = cleanText(line, { field, label: `標題第 ${i + 1} 行`, limit: LIMITS.headline, required: true }, req, issues);
    return pick(field, text, fallback.headline[i]);
  }) as [string, string];
  const subhead = pick('subhead', cleanText(draft.subhead, { field: 'subhead', label: '副標', limit: LIMITS.subhead }, req, issues), fallback.subhead);

  const featureFields = draft.features.slice(0, 3).map((f, i) => {
    const field = `features.${i}`;
    return { field, text: cleanText(f, { field, label: `賣點第 ${i + 1} 項`, limit: LIMITS.feature }, req, issues) };
  });
  const features = featureFields.some(({ field }) => issues.failed(field))
    ? fallback.features
    : featureFields.map((f) => f.text).filter((t) => t !== '');

  const top = pick('badge.top', cleanText(draft.badge.top, { field: 'badge.top', label: '徽章上方文字', limit: LIMITS.badgeTop }, req, issues), fallback.badge.top);
  // 需求有優惠時徽章主文固定為該優惠（使用者的資料，不改寫）
  const main = brief.offer
    ?? pick('badge.main', cleanText(draft.badge.main, { field: 'badge.main', label: '徽章主文', limit: LIMITS.badgeMain, required: true }, req, issues), fallback.badge.main);
  const sub = pick('badge.sub', cleanBadgeSub(draft.badge.sub, req, issues), fallback.badge.sub);
  const label = pick('priceLabel', cleanText(draft.priceLabel, { field: 'priceLabel', label: '價格標籤', limit: LIMITS.priceLabel }, req, issues), fallback.price.label);

  // 商品名稱是使用者的資料：只移除 emoji，其他缺字保留並警告
  const productName = stripEmoji(product.name);
  if (productName !== product.name) issues.add('emoji_removed', 'productName', `商品名稱「${product.name}」有 emoji`, false);
  const missing = missingGlyphs(productName);
  if (missing.length) {
    issues.add('product_glyph', 'productName', `商品名稱「${productName}」有伺服器字型沒有的字：「${missing.join('')}」`, false);
  }

  const badge = { top, main, sub };
  return {
    headline, subhead, features, badge,
    price: { label, sale: product.price.sale, original: product.price.original },
    productName,
    disclaimer: buildDisclaimer(brand, brief, { headline, subhead, features, badge }),
  };
}

const Z_INDEX: Partial<Record<LayoutElementId, number>> = { product: 1, badge: 3 };
const name = (id: LayoutElementId) => `「${ELEMENT_LABELS[id]}」`;

/** 結構與幾何：8 個元素各一次、整數、寬高 > 0、完全在畫布內、彼此不相交 */
function layoutProblems(draft: SpecDraft['layout'], width: number, height: number): string[] {
  const problems: string[] = [];
  const missing = LAYOUT_ELEMENT_IDS.filter((id) => !draft.some((b) => b.id === id));
  if (missing.length) problems.push(`版面缺少元素：${missing.map((id) => ELEMENT_LABELS[id]).join('、')}`);
  for (const id of LAYOUT_ELEMENT_IDS) {
    const count = draft.filter((b) => b.id === id).length;
    if (count > 1) problems.push(`${name(id)}出現 ${count} 次`);
  }
  const unknown = draft.filter((b) => !(LAYOUT_ELEMENT_IDS as readonly string[]).includes(b.id));
  if (unknown.length) problems.push(`版面有不認得的元素：${unknown.map((b) => b.id).join('、')}`);
  if (problems.length) return problems;

  for (const { id, bbox } of draft) {
    if (bbox.length !== 4 || !bbox.every(Number.isInteger)) problems.push(`${name(id)}的方框必須是 4 個整數：${JSON.stringify(bbox)}`);
    else if (bbox[2] <= 0 || bbox[3] <= 0) problems.push(`${name(id)}的方框寬高必須大於 0`);
    else if (!isInside(toRect(bbox), width, height)) problems.push(`${name(id)}的方框超出畫布（${width} × ${height}）`);
  }
  if (problems.length) return problems;

  const ordered = LAYOUT_ELEMENT_IDS.map((id) => draft.find((b) => b.id === id)!);
  ordered.forEach((a, i) => ordered.slice(i + 1).forEach((b) => {
    if (intersectionArea(toRect(a.bbox), toRect(b.bbox)) > 0) problems.push(`${name(a.id)}與${name(b.id)}的方框重疊，請分開`);
  }));
  return problems;
}

/** 版面規則（與審查的三項規則同一個函式）不通過時的說明 */
function ruleProblems(spec: Pick<PromptSpec, 'canvas' | 'layout'>, brand: Brand): string[] {
  const [lo, hi] = brand.rules.productRatio.map((v) => round1(v * 100));
  return layoutRuleChecks(spec, brand).filter((c) => c.status !== 'pass').map((c) => {
    if (c.id === 'product_ratio') return `商品框佔畫面 ${c.value}，品牌規範為 ${lo}%–${hi}%`;
    if (c.id === 'whitespace') return `留白比例 ${c.value}，品牌規範為 ≥ ${round1(brand.rules.minWhitespace * 100)}%`;
    const need = c.rule.replace(/^間距 /, '需 ');
    return c.value.startsWith('與標題重疊') ? `Logo ${c.value}，${need}` : `Logo 與標題的${c.value}，${need}`;
  });
}

/** 依實際文案排版後的字級：標題 ≥ 短邊 × TEXT_MIN.headline，其他文字 ≥ 短邊 × TEXT_MIN.other（徽章英文除外） */
function sizeProblems(spec: Pick<PromptSpec, 'canvas' | 'layout' | 'palette' | 'copy'>, brand: Brand): string[] {
  const short = Math.min(spec.canvas.width, spec.canvas.height);
  const scene = composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: spec.copy, brand });
  const texts: TextOp[] = scene.ops.flatMap((op) =>
    op.kind === 'text' ? [op] : op.kind === 'badge' ? op.texts : op.kind === 'logo' && op.wordmark ? [op.wordmark] : [],
  );
  const problems = new Map<LayoutElementId, string>();
  for (const op of texts) {
    if (op.el === 'badge' && op.text === spec.copy.badge.sub) continue;
    const min = short * (op.el === 'headline' ? TEXT_MIN.headline : TEXT_MIN.other);
    if (op.size < min && !problems.has(op.el)) {
      problems.set(op.el, `${ELEMENT_LABELS[op.el]}的字級只有 ${round1(op.size)}px（框太小或文字太長），需 ≥ ${round1(min)}px`);
    }
  }
  return [...problems.values()];
}

function guardLayout(draft: SpecDraft, req: GuardRequest, copy: Copy, issues: Issues): LayoutBox[] {
  const template = getTemplate(req.templateId);
  const canvas = { width: template.width, height: template.height, ratio: template.ratio };
  const fallback = computeLayout(template);

  const invalid = layoutProblems(draft.layout, template.width, template.height);
  if (invalid.length) {
    issues.add('layout_invalid', 'layout', invalid.join('；'), true);
    return fallback;
  }
  const layout = LAYOUT_ELEMENT_IDS.map((id): LayoutBox => {
    const bbox = draft.layout.find((b) => b.id === id)!.bbox;
    return { id, bbox: [...bbox] as BBox, z: Z_INDEX[id] ?? 2 };
  });
  const rules = ruleProblems({ canvas, layout }, req.brand);
  if (rules.length) issues.add('layout_rule', 'layout', rules.join('；'), true);
  const sizes = sizeProblems({ canvas, layout, palette: req.brand.palette, copy }, req.brand);
  if (sizes.length) issues.add('text_too_small', 'layout', sizes.join('；'), true);
  return rules.length || sizes.length ? fallback : layout;
}

/** 英文的提示詞片段；不合法時記 prompt_invalid 並捨棄 */
function englishOrNull(text: string, field: string, label: string, issues: Issues): string | null {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  if (!ENGLISH.test(trimmed)) {
    issues.add('prompt_invalid', field, `${label}必須是英文：「${trimmed}」`, true);
    return null;
  }
  return trimmed;
}

/**
 * Prompt 構建的程式護欄：回傳一定可以直接使用的 PromptSpec，以及發現的問題。
 * 有 retry 問題的欄位已經改用預設值（文案用 buildCopy、版面用 computeLayout、場景用模擬版的句型）；
 * Agent 第一次遇到 retry 問題時帶著 message 重問 Gemini，第二次直接使用這裡的結果。
 */
export function finalizeSpec(draft: SpecDraft, req: GuardRequest): { spec: PromptSpec; issues: GuardIssue[] } {
  const issues = new Issues();
  const template = getTemplate(req.templateId);
  const canvas = { width: template.width, height: template.height, ratio: template.ratio };

  const copy = guardCopy(draft, req, issues);
  const layout = guardLayout(draft, req, copy, issues);
  const scene = englishOrNull(draft.scene, 'scene', '生圖場景（scene）', issues);
  const extra = englishOrNull(draft.negativeExtra, 'negativeExtra', '負向提示詞（negativeExtra）', issues) ?? '';

  const positivePrompt = positivePromptOf(template, req.brand, req.brief, scene);
  const negativePrompt = negativePromptOf(req.fixes, extra);
  const spec: PromptSpec = {
    jobId: req.jobId,
    round: req.round,
    templateId: template.id,
    brandId: req.brand.id,
    canvas,
    palette: { ...req.brand.palette },
    copy,
    layout,
    positivePrompt,
    negativePrompt,
    injection: buildInjection({ positivePrompt, negativePrompt, canvas, layout }, req.engine, req.product.id, req.seed),
    ragRefs: [...req.ragRefs],
  };
  return { spec, issues: issues.list };
}
