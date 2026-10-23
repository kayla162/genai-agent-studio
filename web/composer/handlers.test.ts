import { describe, expect, it } from 'vitest';
import type { Product, PromptSpec, ReviewCheck } from '@/types/contract';
import { planFixes } from '@/lib/agent/fixes';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { finalizeSpec } from '@/lib/agent/guard';
import { composePoster } from '@/lib/compose/scene';
import { expectedSegments } from '@/lib/review/ocr';
import { NO_PRIMARY_MESSAGE, runRuleChecks } from '@/lib/review/rules';
import { contentVlmChecks, geminiVlmChecks } from '@/lib/review/vlm';
import { cleanSpec, draftOf, passingVerdict } from '@/test/fixtures';
import { handle } from './handlers';

const serum = SAMPLE_PRODUCTS[0] as Product;
const brief = parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum);
const promptBody = (flawed: boolean) => ({
  jobId: 'job_c', round: 1, brand: SELUNE, product: serum, brief, templateId: 'ig-post' as const, engine: 'comfyui' as const,
  seed: 123456789, ragRefs: ['selune#color'], fixes: [], flawed,
});

describe('composer handlers', () => {
  it('returns the preset layout of a template', () => {
    expect(handle('/layout', { templateId: 'story' })).toEqual(computeLayout(getTemplate('story')));
  });

  it('parses a brief like the mock', () => {
    expect(handle('/sim/brief', { brand: SELUNE, product: serum, text: '週年慶主打買一送一，溫柔療癒' })).toEqual(brief);
    expect(handle('/sim/brief', { brand: SELUNE, product: null, text: '隨便' })).toMatchObject({ productName: null });
  });

  it('builds a clean spec, or a flawed one for the first round of the demo', () => {
    const clean = handle('/sim/prompt', promptBody(false)) as PromptSpec;
    expect(clean).toEqual(buildPromptSpec({ ...promptBody(false), template: getTemplate('ig-post'), engine: 'comfyui', fixes: [] }));
    const flawed = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    expect(flawed.palette.primary).toBe('#E0458A');
    expect(flawed.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('reviews and plans fixes like the mock', () => {
    const spec = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    const full = reviewRender(spec, SELUNE, 1, 42);
    const review = handle('/sim/review', { spec, brand: SELUNE, variant: 1, seed: 42 }) as { checks: ReviewCheck[] };
    expect(review).toEqual({ checks: full.checks, score: full.score, passed: full.passed });
    expect(handle('/sim/fixes', { checks: review.checks, brand: SELUNE, spec })).toEqual(planFixes(review.checks, SELUNE, spec));
  });

  it('reviews a poster with 7 rules and 3 content checks, without score jitter', () => {
    const spec = cleanSpec();
    const review = handle('/review', { spec, brand: SELUNE, measuredPrimary: '#b76e79' }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    expect(review.checks).toEqual([
      ...runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#b76e79' }), ...contentVlmChecks(spec, SELUNE),
    ]);
    expect(review.checks.map((c) => c.status).every((s) => s === 'pass')).toBe(true);
    expect(review).toMatchObject({ score: 100, passed: true });
  });

  it('fails the flawed first round with the measured off-brand primary, with the score of scoreChecks(checks, 0)', () => {
    const spec = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    const review = handle('/review', { spec, brand: SELUNE, measuredPrimary: '#e0458a' }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    const failed = review.checks.filter((c) => c.status === 'fail').map((c) => c.id);
    expect(failed).toEqual(['banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion']);
    expect(review.checks.find((c) => c.id === 'color_delta')!.value).toBe('ΔE 12.5 · 偵測主色 #E0458A');
    const warned = review.checks.filter((c) => c.status === 'warn').length;
    expect(review).toMatchObject({ score: 100 - 14 * failed.length - 6 * warned, passed: false });
  });

  it('fails color_delta when no primary was measured', () => {
    const review = handle('/review', { spec: cleanSpec(), brand: SELUNE, measuredPrimary: null }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    const color = review.checks.find((c) => c.id === 'color_delta')!;
    expect(color).toMatchObject({ status: 'fail', value: NO_PRIMARY_MESSAGE });
    expect(review).toMatchObject({ score: 86, passed: false });
  });

  it('rejects a measured primary that is not a hex colour or null', () => {
    for (const measuredPrimary of [undefined, 'pink', '#b76e7', 42]) {
      expect(() => handle('/review', { spec: cleanSpec(), brand: SELUNE, measuredPrimary })).toThrow(/measuredPrimary 必須是 #RRGGBB 或 null/);
    }
  });

  it('finalizes a Gemini draft with the guard', () => {
    const request = { ...promptBody(false), text: '週年慶主打買一送一，溫柔療癒' };
    const draft = draftOf(cleanSpec());
    expect(handle('/spec', { draft, request })).toEqual(finalizeSpec(draft, request));
    const bad = { ...draft, headline: ['这一夜修護', '醒來透亮發光✨'] };
    const { spec, issues } = handle('/spec', { draft: bad, request }) as ReturnType<typeof finalizeSpec>;
    expect(issues.map((i) => i.code)).toEqual(['missing_glyph', 'emoji_removed']);
    expect(spec.copy.headline).toEqual(['一夜溫柔修護', '醒來透亮發光']);
  });

  it('rejects a malformed draft or request with a Chinese message', () => {
    const request = { ...promptBody(false), text: '' };
    const draft = draftOf(cleanSpec());
    expect(() => handle('/spec', { draft: { ...draft, layout: 'x' }, request })).toThrow('draft.layout 必須是陣列');
    expect(() => handle('/spec', { draft: { ...draft, headline: ['只有一行'] }, request })).toThrow('draft.headline 必須是 2 個字串');
    expect(() => handle('/spec', { draft, request: { ...request, templateId: 'poster' } })).toThrow('request.templateId 不是可用的模板：poster');
    expect(() => handle('/spec', { draft: null, request })).toThrow('draft 必須是物件');
  });

  it('reviews with the Gemini verdict and the transcription when vlm is given', () => {
    const spec = cleanSpec();
    const segments = expectedSegments(composePoster({ ...spec, brand: SELUNE }));
    const verdict = passingVerdict(segments.map((s) => s.text));
    const review = handle('/review', { spec, brand: SELUNE, measuredPrimary: '#b76e79', vlm: verdict, vlmScale: 1 }) as {
      checks: ReviewCheck[]; score: number; passed: boolean;
    };
    expect(review.checks.slice(8)).toEqual(geminiVlmChecks(verdict, spec, SELUNE));
    expect(review.checks.find((c) => c.id === 'ocr_typo')).toMatchObject({ value: '0 處差異', status: 'pass' });
    // 沒有傳入背景量測時，只有背景色系是模擬
    expect(review.checks.filter((c) => c.value.includes('模擬')).map((c) => c.id)).toEqual(['bg_palette']);
    expect(review).toMatchObject({ score: 100, passed: true });

    const boxed = handle('/review', {
      spec, brand: SELUNE, measuredPrimary: '#b76e79', vlm: passingVerdict([...verdict.lines, '□']),
    }) as { checks: ReviewCheck[]; passed: boolean };
    expect(boxed.checks.find((c) => c.id === 'ocr_typo')).toMatchObject({ status: 'fail', target: 'canvas' });
    expect(boxed.passed).toBe(false);

    expect(handle('/review', { spec, brand: SELUNE, measuredPrimary: '#b76e79', vlm: null }))
      .toEqual(handle('/review', { spec, brand: SELUNE, measuredPrimary: '#b76e79' }));
    expect(() => handle('/review', { spec, brand: SELUNE, measuredPrimary: null, vlm: { ...verdict, lines: 'x' } }))
      .toThrow('vlm.lines 必須是字串陣列');
    expect(() => handle('/review', { spec, brand: SELUNE, measuredPrimary: null, vlm: verdict, vlmScale: 0 }))
      .toThrow('vlmScale 必須是大於 0 的數字');
  });

  it('plans fixes like /sim/fixes', () => {
    const spec = handle('/sim/prompt', promptBody(true)) as PromptSpec;
    const { checks } = handle('/sim/review', { spec, brand: SELUNE, variant: 1, seed: 42 }) as { checks: ReviewCheck[] };
    expect(handle('/fixes', { checks, brand: SELUNE, spec })).toEqual(handle('/sim/fixes', { checks, brand: SELUNE, spec }));
  });

  it('lists the characters the poster fonts lack for each text', () => {
    expect(handle('/glyphs', { texts: ['晞月透亮', '这样😀', ''] })).toEqual({ missing: [[], ['这', '😀'], []] });
    expect(() => handle('/glyphs', { texts: 'x' })).toThrow('texts 必須是字串陣列');
  });

  it('rejects unknown routes', () => {
    expect(() => handle('/nope', {})).toThrow('Unknown route: /nope');
  });
});
