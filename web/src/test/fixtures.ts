import type { Brand, Product, PromptSpec, TemplateId } from '@/types/contract';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';

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

/** 由 buildPromptSpec 產生的合規 spec（週年慶買一送一、溫柔語氣） */
export function cleanSpec(brand: Brand = SELUNE, product: Product = SERUM, templateId: TemplateId = 'ig-post'): PromptSpec {
  return buildPromptSpec({
    jobId: 'job_t', round: 1, brand, product, brief: parseBrief('週年慶主打買一送一，溫柔療癒', brand, product),
    template: getTemplate(templateId), engine: 'comfyui', seed: 42, ragRefs: [], fixes: [],
  });
}
