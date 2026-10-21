import { describe, expect, it } from 'vitest';
import type { Product, PromptSpec, ReviewCheck } from '@/types/contract';
import { planFixes } from '@/lib/agent/fixes';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { handle } from './handlers';

const serum = SAMPLE_PRODUCTS[0] as Product;
const brief = parseBrief('週年慶主打買一送一，溫柔療癒', SELUNE, serum);
const promptBody = (flawed: boolean) => ({
  jobId: 'job_c', round: 1, brand: SELUNE, product: serum, brief, templateId: 'ig-post', engine: 'comfyui',
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

  it('rejects unknown routes', () => {
    expect(() => handle('/nope', {})).toThrow('Unknown route: /nope');
  });
});
