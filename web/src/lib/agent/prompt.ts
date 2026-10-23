import type {
  Brand, ChannelTemplate, CheckId, ComfyInjection, Copy, Engine, ParsedBrief, Product, PromptSpec,
} from '@/types/contract';
import { computeLayout } from '@/lib/compose/layout';
import { claimTexts, hasClaim } from '@/lib/review/rules';

export const BASE_NEGATIVE = 'lowres, blurry, watermark, deformed product, extra objects, garbled text';

const OFFER_SUB: [RegExp, string][] = [
  [/買一送一/, 'BUY 1 GET 1'],
  [/買二送一/, 'BUY 2 GET 1'],
  [/折/, 'SPECIAL PRICE'],
];

/** 上一輪未通過的檢查 → 這一輪 negative prompt 要加強的詞 */
export const NEGATIVE_BY_FIX: Partial<Record<CheckId, string>> = {
  color_delta: 'oversaturated, neon, off-brand colors',
  bg_palette: 'neon colors, fluorescent colors, off-brand color cast',
  vlm_occlusion: 'cluttered composition, overlapping elements',
  vlm_quality: 'overexposed highlights',
};

export function makeBadge(brief: ParsedBrief): Copy['badge'] {
  const offer = brief.offer;
  return {
    top: brief.campaign ? `${brief.campaign}限定` : '期間限定',
    main: offer ?? '限時優惠',
    sub: (offer && OFFER_SUB.find(([re]) => re.test(offer))?.[1]) || 'LIMITED OFFER',
  };
}

/** 依品牌的合規替代用語改寫文字（替代詞為空字串時直接刪除該詞） */
export function applyReplacements(text: string, replacements: Record<string, string>): string {
  return Object.entries(replacements).reduce((s, [word, alt]) => s.split(word).join(alt), text);
}

export function buildCopy(brand: Brand, product: Product, brief: ParsedBrief, rewrite = false): Copy {
  const preset = brand.copyPresets[brief.tone];
  // 上一輪文案審查未通過時，依品牌替代用語改寫；商品名稱是登錄的商品資料，不改寫
  const fix = (text: string) => (rewrite ? applyReplacements(text, brand.replacements) : text);
  const headline: [string, string] = [fix(preset.headline[0]), fix(preset.headline[1])];
  const subhead = fix(preset.subhead);
  const features = (brief.sellingPoints.length ? brief.sellingPoints : product.features)
    .slice(0, 3)
    .map(fix)
    .filter((f) => f !== '');
  const baseBadge = makeBadge(brief);
  const badge = { ...baseBadge, top: fix(baseBadge.top), main: fix(baseBadge.main) };
  return {
    headline,
    subhead,
    features,
    badge,
    price: { label: fix(`${brief.campaign ?? '限時'}活動價`), sale: product.price.sale, original: product.price.original },
    productName: product.name,
    disclaimer: buildDisclaimer(brand, brief, { headline, subhead, features, badge }),
  };
}

/** 頁尾註記：效果宣稱的說明、活動期間、數量有限。宣稱範圍與審查（runRuleChecks）相同，確保需要註記時一定會加上 */
export function buildDisclaimer(
  brand: Brand, brief: ParsedBrief, copy: Pick<Copy, 'headline' | 'subhead' | 'features' | 'badge'>,
): string {
  const claim = hasClaim(claimTexts(copy), brand.claimWords);
  const notes = [
    claim && brand.disclaimerPhrase ? `*使用者感受，${brand.disclaimerPhrase}` : null,
    brief.period ? `活動期間 ${brief.period}` : null,
    brief.offer ? '數量有限，售完為止' : null,
  ].filter((s): s is string => s !== null);
  return notes.length ? notes.join('｜') : '圖片僅供參考';
}

/**
 * 正向提示詞：程式固定的開頭（比例、商品攝影、提供的商品照）＋ 場景 ＋ 品牌視覺風格 ＋ 色票 ＋ 需求的風格 ＋ 固定的結尾。
 * scene 為 null 時就是模擬版的提示詞句型（Gemini 的場景描述不合法時也用它）。
 */
export function positivePromptOf(template: ChannelTemplate, brand: Brand, brief: ParsedBrief, scene: string | null): string {
  const palette = brand.palette;
  return [
    `${template.ratio} commercial product photography`,
    'the provided product photo on a styled surface',
    ...(scene ? [scene] : []),
    brand.visualStyle,
    `${palette.primary} and ${palette.secondary} color palette with ${palette.accent} accents`,
    ...brief.style,
    'clean negative space for typography',
    'high-end editorial lighting',
  ].join(', ');
}

/** 負向提示詞：BASE_NEGATIVE ＋ 依先前未通過的檢查加強的詞 ＋ extra，以逗號拆開後去除空白與重複 */
export function negativePromptOf(fixes: CheckId[], extra = ''): string {
  const parts = [BASE_NEGATIVE, ...fixes.map((id) => NEGATIVE_BY_FIX[id] ?? ''), extra]
    .flatMap((s) => s.split(','))
    .map((s) => s.trim())
    .filter((s) => s !== '');
  return [...new Set(parts)].join(', ');
}

export interface PromptBuildInput {
  jobId: string;
  round: number;
  brand: Brand;
  product: Product;
  brief: ParsedBrief;
  template: ChannelTemplate;
  engine: Engine;
  seed: number;
  ragRefs: string[];
  /** 上一輪未通過的檢查 id，用來加強 negative prompt */
  fixes: CheckId[];
}

export function buildInjection(
  spec: Pick<PromptSpec, 'positivePrompt' | 'negativePrompt' | 'canvas' | 'layout'>,
  engine: Engine,
  productId: string,
  seed: number,
): ComfyInjection {
  const { width, height, ratio } = spec.canvas;
  if (engine === 'ideogram') {
    return {
      engine,
      workflowFile: 'ideogram/v4/generate',
      params: [
        { nodeId: 'body', input: 'prompt', label: 'positive_prompt', value: spec.positivePrompt },
        { nodeId: 'body', input: 'negative_prompt', label: 'negative_prompt', value: spec.negativePrompt },
        { nodeId: 'body', input: 'aspect_ratio', label: 'aspect_ratio', value: ratio },
        { nodeId: 'body', input: 'style_type', label: 'style_type', value: 'DESIGN' },
        { nodeId: 'body', input: 'seed', label: 'seed', value: seed },
        { nodeId: 'body', input: 'image_reference', label: 'product_image', value: `${productId}.png` },
      ],
    };
  }
  return {
    engine,
    workflowFile: 'workflows/product_scene_v1.json',
    params: [
      { nodeId: '4', input: 'ckpt_name', label: 'checkpoint', value: 'sd_xl_base_1.0.safetensors' },
      { nodeId: '6', input: 'text', label: 'positive_prompt', value: spec.positivePrompt },
      { nodeId: '7', input: 'text', label: 'negative_prompt', value: spec.negativePrompt },
      { nodeId: '10', input: 'image', label: 'product_image', value: `${productId}.png` },
      { nodeId: '11', input: 'model', label: 'cutout_model', value: 'BiRefNet-general' },
      { nodeId: '14', input: 'strength', label: 'controlnet_depth', value: 0.65 },
      { nodeId: '15', input: 'weight', label: 'ip_adapter_style', value: 0.55 },
      { nodeId: '20', input: 'width', label: 'width', value: width },
      { nodeId: '20', input: 'height', label: 'height', value: height },
      { nodeId: '3', input: 'seed', label: 'seed', value: seed },
      { nodeId: '3', input: 'sampler_name', label: 'sampler', value: 'dpmpp_2m_sde' },
      { nodeId: '3', input: 'steps', label: 'steps', value: 28 },
      { nodeId: '3', input: 'cfg', label: 'cfg', value: 6 },
      { nodeId: '30', input: 'light_direction', label: 'ic_light', value: 'top-left' },
      { nodeId: '40', input: 'boxes', label: 'layout_boxes', value: JSON.stringify(spec.layout.map((b) => [b.id, ...b.bbox])) },
    ],
  };
}

export function setParam(injection: ComfyInjection, label: string, value: string | number): ComfyInjection {
  return { ...injection, params: injection.params.map((p) => (p.label === label ? { ...p, value } : p)) };
}

export const seedOf = (spec: PromptSpec): number =>
  Number(spec.injection.params.find((p) => p.label === 'seed')?.value ?? 0);

export function buildPromptSpec(input: PromptBuildInput): PromptSpec {
  const { brand, product, brief, template } = input;
  const palette = { ...brand.palette };
  const layout = computeLayout(template);
  const positivePrompt = positivePromptOf(template, brand, brief, null);
  const negativePrompt = negativePromptOf(input.fixes);
  const rewrite = input.fixes.some((id) => id === 'banned_words' || id === 'vlm_exaggeration');
  const canvas = { width: template.width, height: template.height, ratio: template.ratio };

  return {
    jobId: input.jobId,
    round: input.round,
    templateId: template.id,
    brandId: brand.id,
    canvas,
    palette,
    copy: buildCopy(brand, product, brief, rewrite),
    layout,
    positivePrompt,
    negativePrompt,
    injection: buildInjection({ positivePrompt, negativePrompt, canvas, layout }, input.engine, product.id, input.seed),
    ragRefs: [...input.ragRefs],
  };
}
