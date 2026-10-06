import type { Brand, ParsedBrief, Product, Tone } from '@/types/contract';

/** 依序比對，第一個命中的規則決定語氣 */
const TONE_RULES: [RegExp, Tone][] = [
  [/簡約|極簡|minimal/i, 'minimal'],
  [/溫柔|療癒|柔和/, 'gentle'],
  [/科研|專業|成分|科學/, 'science'],
  [/活潑|年輕|可愛|有趣/, 'playful'],
];

const STYLE_WORDS: [zh: string, en: string][] = [
  ['簡約', 'minimal'], ['高級感', 'premium'], ['溫柔', 'soft'], ['清新', 'fresh'],
  ['奢華', 'luxury'], ['復古', 'vintage'], ['療癒', 'healing'], ['科技感', 'futuristic'],
];

const CAMPAIGN_RE = /週年慶|雙\s*11|中秋|母親節|聖誕|新品上市|夏季|開學/;
const OFFER_RE = /買一送一|買二送一|第二件\s*\d+(?:\.\d+)?\s*折|\d+(?:\.\d+)?\s*折/;
const AUDIENCE_RE = /(?:給|針對|適合)([^，。,.！!]+)/;

/** 以關鍵字規則模擬 LLM 的需求拆解（第二階段改由後端 LLM 產生同格式結果） */
export function parseBrief(text: string, brand: Brand, product: Product | null): ParsedBrief {
  const tone = TONE_RULES.find(([re]) => re.test(text))?.[1] ?? brand.defaultTone;
  const campaign = text.match(CAMPAIGN_RE)?.[0].replace(/\s+/g, '') ?? null;
  const offer = text.match(OFFER_RE)?.[0].replace(/\s+/g, '') ?? null;
  const audience = text.match(AUDIENCE_RE)?.[1].trim() ?? '一般消費者';
  const style = STYLE_WORDS.filter(([zh]) => text.includes(zh)).map(([, en]) => en);

  const features = product?.features ?? [];
  const mentioned = features.filter((f) => text.includes(f));
  const sellingPoints = [...mentioned, ...features.filter((f) => !mentioned.includes(f))].slice(0, 3);

  return { productName: product?.name ?? null, sellingPoints, audience, tone, campaign, offer, style };
}
