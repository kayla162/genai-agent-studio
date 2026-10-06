import { describe, it, expect } from 'vitest';
import type { JobEvent, JobInput } from '@/types/contract';
import { getTemplate } from '@/lib/compose/templates';
import { SELUNE, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { buildTimeline, type ScenarioContext, type TimedEvent } from './scenario';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const BRIEF = '週年慶主打買一送一，溫柔療癒';

const ctx = (over: Partial<ScenarioContext> = {}, input: Partial<JobInput> = {}): ScenarioContext => ({
  jobId: 'job_test',
  seed: 7,
  brand: SELUNE,
  product: serum,
  templates: [getTemplate('ig-post')],
  demo: { speed: 1, firstRoundFail: true, forceAllFail: false },
  input: {
    brandId: 'selune', productId: serum.id, brief: BRIEF, parsedBrief: parseBrief(BRIEF, SELUNE, serum),
    templateIds: ['ig-post'], variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui',
    vlm: 'Gemini 3.7 Vision', maxRetries: 2, ...input,
  },
  ...over,
});

function ofType<T extends JobEvent['type']>(tl: TimedEvent[], type: T): Extract<JobEvent, { type: T }>[] {
  return tl.map((x) => x.event).filter((e): e is Extract<JobEvent, { type: T }> => e.type === type);
}

describe('buildTimeline (default demo)', () => {
  const tl = buildTimeline(ctx());

  it('fails round 1, rewrites once, passes round 2 and ends at 14.5 s', () => {
    expect(tl[0].event).toEqual({ type: 'job.accepted', jobId: 'job_test' });
    expect(tl.at(-1)!.at).toBe(14_500);
    const reviews = ofType(tl, 'review.completed');
    expect(reviews.filter((e) => e.round === 1).every((e) => !e.passed)).toBe(true);
    expect(reviews.filter((e) => e.round === 2).some((e) => e.passed)).toBe(true);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });

  it('emits stages in pipeline order', () => {
    expect(ofType(tl, 'job.status').map((e) => e.stage)).toEqual([
      'parsing', 'retrieving',
      'prompting', 'rendering', 'composing', 'reviewing', 'rewriting',
      'prompting', 'rendering', 'composing', 'reviewing',
      'saving', 'done',
    ]);
  });

  it('never goes back in time', () => {
    for (let i = 1; i < tl.length; i++) expect(tl[i].at).toBeGreaterThanOrEqual(tl[i - 1].at);
  });

  it('reranks RAG hits and re-queries compliant wording before the rewrite', () => {
    const [first, requery] = ofType(tl, 'rag.retrieved');
    const [reranked] = ofType(tl, 'rag.reranked');
    expect(first.hits.map((h) => h.tag)).toEqual(['layout', 'color', 'history', 'logo', 'law']);
    expect(reranked.hits.map((h) => h.tag)).toEqual(['color', 'law', 'logo', 'layout', 'history']);
    expect(requery.hits[0].chunkId).toBe('selune#law-alt');
    const round2 = ofType(tl, 'prompt.generated').find((e) => e.round === 2)!;
    expect(round2.spec.ragRefs).toContain('selune#law-alt');
    expect(round2.spec.negativePrompt).toContain('off-brand colors');
    expect(round2.spec.palette).toEqual(SELUNE.palette);
  });

  it('emits 38 render progress steps per round, ending with upscale', () => {
    const r1 = ofType(tl, 'render.progress').filter((e) => e.round === 1);
    expect(r1).toHaveLength(38);
    expect(r1.at(-1)).toMatchObject({ node: 'upscale', step: 2, maxStep: 2 });
  });

  it('is deterministic for the same seed', () => {
    expect(buildTimeline(ctx())).toEqual(tl);
  });
});

describe('buildTimeline (other demo options)', () => {
  it('finishes in 8.2 s with no rewrite when round 1 is clean', () => {
    const tl = buildTimeline(ctx({ demo: { speed: 1, firstRoundFail: false, forceAllFail: false } }));
    expect(tl.at(-1)!.at).toBe(8_200);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(0);
    expect(ofType(tl, 'job.completed')).toHaveLength(1);
  });

  it('ends with needs_review after maxRetries when every round fails', () => {
    const tl = buildTimeline(ctx({ demo: { speed: 1, firstRoundFail: true, forceAllFail: true } }, { maxRetries: 1 }));
    expect(ofType(tl, 'job.needs_review')).toHaveLength(1);
    expect(ofType(tl, 'job.completed')).toHaveLength(0);
    expect(ofType(tl, 'rewrite.started')).toHaveLength(1);
    expect(ofType(tl, 'job.status').at(-1)).toEqual({ type: 'job.status', stage: 'needs_review', round: 2 });
  });

  it('picks the best passing render for each template', () => {
    const tl = buildTimeline(ctx({ templates: [getTemplate('ecom-main'), getTemplate('story')] }, { templateIds: ['ecom-main', 'story'] }));
    const [done] = ofType(tl, 'job.completed');
    expect(Object.keys(done.bestRenderIds).sort()).toEqual(['ecom-main', 'story']);
    expect(done.bestRenderIds['ecom-main']).toMatch(/^job_test_r2_ecom-main_v\d$/);
    expect(ofType(tl, 'render.completed').flatMap((e) => e.renders)).toHaveLength(16);
  });
});
