import type {
  Brand, DemoOptions, Engine, JobInput, JobMessage, JobStage, Product, PromptSpec, TemplateId,
} from '@/types/contract';
import type { SpecDraft, VlmVerdict } from '@/types/agent';
import type { JobSnapshot } from '@/lib/api/client';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { getBrandById, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';

/** 一份「合規」的 SÉLUNE PromptSpec，測試時再用 overrides 製造問題 */
export function makeSpec(overrides: Partial<PromptSpec> = {}, templateId: TemplateId = 'ig-post'): PromptSpec {
  const t = getTemplate(templateId);
  return {
    jobId: 'job_test',
    round: 1,
    templateId: t.id,
    brandId: SELUNE.id,
    canvas: { width: t.width, height: t.height, ratio: t.ratio },
    palette: { ...SELUNE.palette },
    copy: {
      headline: ['一夜溫柔修護', '醒來透亮發光'],
      subhead: '7天感受透亮光采・專業修護配方*',
      features: ['5重玻尿酸', '神經醯胺', '無香精'],
      badge: { top: '週年慶限定', main: '買一送一', sub: 'BUY 1 GET 1' },
      price: { label: '週年慶活動價', sale: 1280, original: 1680 },
      productName: '極光玻尿酸修護精華 30ml',
      disclaimer: '*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15',
    },
    layout: computeLayout(t),
    positivePrompt: 'test prompt',
    negativePrompt: 'lowres',
    injection: { engine: 'comfyui', workflowFile: 'workflows/product_scene_v1.json', params: [] },
    ragRefs: [],
    ...overrides,
  };
}

const SERUM = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;

/** 由 buildPromptSpec 產生的合規 spec（週年慶 2026/10/15–11/15 買一送一、溫柔語氣） */
export function cleanSpec(brand: Brand = SELUNE, product: Product = SERUM, templateId: TemplateId = 'ig-post'): PromptSpec {
  return buildPromptSpec({
    jobId: 'job_t', round: 1, brand, product, brief: parseBrief('週年慶 2026/10/15–11/15 主打買一送一，溫柔療癒', brand, product),
    template: getTemplate(templateId), engine: 'comfyui', seed: 42, ragRefs: [], fixes: [], visualStyleId: brand.visualStyles[0].id,
  });
}

/** 把 PromptSpec 的文案與版面轉成 Gemini 的 SpecDraft（護欄不會有意見的 draft） */
export function draftOf(spec: PromptSpec, scene = 'serum bottle on a pearl tray with soft aurora light'): SpecDraft {
  const { copy } = spec;
  return {
    headline: [...copy.headline], subhead: copy.subhead, features: [...copy.features], badge: { ...copy.badge },
    priceLabel: copy.price.label, layout: spec.layout.map((b) => ({ id: b.id, bbox: [...b.bbox] })), scene,
    negativeExtra: '', rationale: '商品放右下，標題靠左對齊網格',
  };
}

/** VLM 的判讀：三項通過，轉錄為 lines */
export function passingVerdict(lines: string[]): VlmVerdict {
  return {
    lines,
    exaggeration: { status: 'pass', phrases: [], reason: '' },
    occlusion: { status: 'pass', elements: [], reason: '' },
    quality: { status: 'pass', issues: [], reason: '' },
  };
}

export interface JobFixture {
  brandId?: string;
  templateIds?: TemplateId[];
  variants?: number;
  engine?: Engine;
  maxRetries?: number;
  demo?: Partial<DemoOptions>;
  jobId?: string;
  createdAt?: string;
  /** 只取前 n 則訊息，模擬執行中的任務 */
  upTo?: number;
}

/** 依 mock 劇本產生一個任務的完整訊息（時間戳以 1× 計）；預設首輪失敗、第二輪通過 */
export function makeJobSnapshot(f: JobFixture = {}): JobSnapshot {
  const brand = getBrandById(f.brandId ?? 'selune');
  const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id)!;
  const jobId = f.jobId ?? 'job_fixture';
  const createdAt = f.createdAt ?? '2026-10-05T01:30:00.000Z';
  const brief = brand.id === 'selune' ? '週年慶主打買一送一，溫柔療癒' : '幫我設計一款簡約風格的冷萃咖啡宣傳海報';
  const input: JobInput = {
    brandId: brand.id, productId: product.id, brief, parsedBrief: parseBrief(brief, brand, product),
    templateIds: f.templateIds ?? ['ig-post'], variantsPerTemplate: f.variants ?? 4, llm: 'Gemini 3.7 Flash',
    engine: f.engine ?? 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: f.maxRetries ?? 2, visualStyleId: null,
  };
  const timeline = buildTimeline({
    jobId, input, brand, product, templates: input.templateIds.map((id) => getTemplate(id)),
    demo: { speed: 1, firstRoundFail: true, forceAllFail: false, ...f.demo }, seed: 1,
  });
  const t0 = Date.parse(createdAt);
  const events: JobMessage[] = timeline
    .slice(0, f.upTo ?? timeline.length)
    .map(({ at, event }, i) => ({ ...event, seq: i + 1, ts: new Date(t0 + at).toISOString() }));
  let stage: JobStage = 'parsing';
  let round = 0;
  let bestRenderIds: JobSnapshot['summary']['bestRenderIds'] = {};
  for (const e of events) {
    if (e.type === 'job.status') ({ stage, round } = e);
    if (e.type === 'job.completed') bestRenderIds = e.bestRenderIds;
  }
  const finished = stage === 'done' || stage === 'needs_review' || stage === 'cancelled';
  return { summary: { id: jobId, input, createdAt, stage, round, finished, bestRenderIds }, events };
}
