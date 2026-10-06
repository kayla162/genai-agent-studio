import { describe, it, expect } from 'vitest';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { getTemplate } from '@/lib/compose/templates';
import { BASE_NEGATIVE, buildPromptSpec, seedOf, setParam, type PromptBuildInput } from './prompt';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;

const input = (over: Partial<PromptBuildInput> = {}): PromptBuildInput => ({
  jobId: 'job_t', round: 1, brand: SELUNE, product: serum,
  brief: parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum),
  template: getTemplate('ig-post'), engine: 'comfyui', seed: 123456789, ragRefs: ['selune#color'], fixes: [],
  ...over,
});
const param = (spec: ReturnType<typeof buildPromptSpec>, label: string) =>
  spec.injection.params.find((p) => p.label === label)?.value;

describe('buildPromptSpec', () => {
  it('builds a compliant SÉLUNE spec from the brand CI and brief', () => {
    const spec = buildPromptSpec(input());
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(spec.layout).toHaveLength(8);
    expect(spec.copy.headline).toEqual(['一夜溫柔修護', '醒來透亮發光']);
    expect(spec.copy.features).toEqual(['5重玻尿酸', '神經醯胺', '無香精']);
    expect(spec.copy.badge).toEqual({ top: '週年慶限定', main: '買一送一', sub: 'BUY 1 GET 1' });
    expect(spec.copy.price).toEqual({ label: '週年慶活動價', sale: 1280, original: 1680 });
    expect(spec.copy.disclaimer).toBe('*使用者感受，效果因個人膚況而異｜活動期間 2026/10/15–11/15｜數量有限，售完為止');
    expect(spec.negativePrompt).toBe(BASE_NEGATIVE);
    expect(spec.ragRefs).toEqual(['selune#color']);
  });

  it('injects prompt, seed, size and layout boxes into the ComfyUI workflow', () => {
    const spec = buildPromptSpec(input());
    expect(spec.injection.workflowFile).toBe('workflows/product_scene_v1.json');
    expect(param(spec, 'positive_prompt')).toBe(spec.positivePrompt);
    expect(param(spec, 'width')).toBe(1440);
    expect(param(spec, 'height')).toBe(1800);
    expect(seedOf(spec)).toBe(123456789);
    expect(JSON.parse(String(param(spec, 'layout_boxes')))).toHaveLength(8);
  });

  it('builds an Ideogram request body when engine is ideogram', () => {
    const spec = buildPromptSpec(input({ engine: 'ideogram' }));
    expect(spec.injection.workflowFile).toBe('ideogram/v4/generate');
    expect(param(spec, 'aspect_ratio')).toBe('4:5');
    expect(seedOf(spec)).toBe(123456789);
  });

  it('keeps the brand palette and strengthens the negative prompt after failures', () => {
    const spec = buildPromptSpec(input({ round: 2, fixes: ['color_delta', 'color_delta', 'vlm_occlusion'] }));
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(spec.negativePrompt).toBe(
      `${BASE_NEGATIVE}, oversaturated, neon, off-brand colors, cluttered composition, overlapping elements`,
    );
    expect(param(spec, 'negative_prompt')).toBe(spec.negativePrompt);
  });

  it('builds minimal coffee copy with no claim note and a default badge', () => {
    const brief = parseBrief('幫我設計一款簡約風格的冷萃咖啡宣傳海報', MISTY_ISLE, coldbrew);
    const spec = buildPromptSpec(input({ brand: MISTY_ISLE, product: coldbrew, brief }));
    expect(spec.copy.headline).toEqual(['一口清醒', '慢萃十八小時']);
    expect(spec.copy.disclaimer).toBe('圖片僅供參考');
    expect(spec.copy.badge).toEqual({ top: '期間限定', main: '限時優惠', sub: 'LIMITED OFFER' });
    expect(spec.copy.price.label).toBe('限時活動價');
    expect(spec.positivePrompt).toContain('minimal');
  });

  it('setParam returns a new injection with the updated value', () => {
    const spec = buildPromptSpec(input());
    const next = setParam(spec.injection, 'seed', 7);
    expect(next.params.find((p) => p.label === 'seed')?.value).toBe(7);
    expect(seedOf(spec)).toBe(123456789);
  });
});
