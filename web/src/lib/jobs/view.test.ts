import { describe, it, expect } from 'vitest';
import type { DemoOptions, JobEvent, JobInput, JobSummary, TemplateId } from '@/types/contract';
import { getTemplate } from '@/lib/compose/templates';
import { SELUNE, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { makeJobSnapshot } from '@/test/fixtures';
import {
  applyEvents, defaultSelection, emptyJobView, finalCandidates, jobProgress, reduceJob, specKey, STAGE_LABEL, withLiveStage,
} from './view';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const BRIEF = '週年慶主打買一送一，溫柔療癒';

function events(demo: Partial<DemoOptions> = {}, input: Partial<JobInput> = {}): JobEvent[] {
  const templateIds: TemplateId[] = input.templateIds ?? ['ig-post', 'story'];
  return buildTimeline({
    jobId: 'job_v', seed: 11, brand: SELUNE, product: serum, templates: templateIds.map(getTemplate),
    demo: { speed: 1, firstRoundFail: true, forceAllFail: false, ...demo },
    input: {
      brandId: 'selune', productId: serum.id, brief: BRIEF, parsedBrief: parseBrief(BRIEF, SELUNE, serum), templateIds,
      variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2, ...input,
    },
  }).map((x) => x.event);
}

describe('reduceJob (default demo: fail → rewrite → pass)', () => {
  const evs = events();
  const v = applyEvents(evs);

  it('ends done in round 2 with one rewrite per template', () => {
    expect(v).toMatchObject({ jobId: 'job_v', stage: 'done', round: 2, outcome: 'done', needsReviewReason: null });
    expect(v.rewrites.map((r) => r.templateId)).toEqual(['ig-post', 'story']);
    expect(v.rewrites[0].fixes.length).toBeGreaterThan(0);
  });

  it('keeps reranked hits and the re-query hit separately', () => {
    expect(v.ragHits).toHaveLength(5);
    expect(v.ragHits.every((h) => h.rerankScore !== undefined)).toBe(true);
    expect(v.requeryHits.map((h) => h.chunkId)).toEqual(['selune#law-alt']);
  });

  it('accumulates checks and scores onto renders', () => {
    expect(v.renderIds).toHaveLength(16);
    for (const id of v.renderIds) {
      expect(v.renders[id].checks).toHaveLength(10);
      expect(v.renders[id].score).not.toBeNull();
    }
    expect(v.specs[specKey(2, 'story')].round).toBe(2);
  });

  it('shows only the final round as candidates and selects the best render', () => {
    const c = finalCandidates(v);
    expect(c['ig-post']!.map((r) => [r.round, r.variant])).toEqual([[2, 0], [2, 1], [2, 2], [2, 3]]);
    expect(defaultSelection(v)).toEqual(v.bestRenderIds);
  });

  it('collects log lines', () => {
    expect(v.logs.length).toBe(evs.filter((e) => e.type === 'log').length);
  });

  it('never mutates the previous view', () => {
    const before = emptyJobView();
    const after = reduceJob(before, { type: 'job.status', stage: 'parsing', round: 0 });
    expect(before.stage).toBeNull();
    expect(after.stage).toBe('parsing');
  });
});

describe('needs review and cancel', () => {
  it('falls back to the highest score when no render passed', () => {
    const v = applyEvents(events({ forceAllFail: true }, { maxRetries: 1, templateIds: ['ig-post'] }));
    expect(v.outcome).toBe('needs_review');
    expect(v.needsReviewReason).toContain('最大重試次數');
    expect(v.bestRenderIds).toEqual({});
    const candidates = finalCandidates(v)['ig-post']!;
    const top = [...candidates].sort((a, b) => b.score! - a.score!)[0];
    expect(defaultSelection(v)['ig-post']).toBe(top.id);
  });

  it('marks a cancelled job', () => {
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'cancelled', round: 1 });
    expect(v.outcome).toBe('cancelled');
  });

  it('marks a failed job and keeps the reason', () => {
    let v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'rendering', round: 1 });
    v = reduceJob(v, { type: 'job.failed', jobId: 'j', reason: 'ComfyUI 沒有回應' });
    v = reduceJob(v, { type: 'job.status', stage: 'failed', round: 1 });
    expect(v).toMatchObject({ outcome: 'failed', stage: 'failed', failureReason: 'ComfyUI 沒有回應' });
    expect(STAGE_LABEL.failed).toBe('失敗');
  });

  it('keeps a queued job running with no progress yet', () => {
    const v = reduceJob(emptyJobView('j'), { type: 'job.status', stage: 'queued', round: 0 });
    expect(v.outcome).toBe('running');
    expect(STAGE_LABEL.queued).toBe('排隊中');
    expect(jobProgress(v)).toBe(0);
  });
});

describe('jobProgress', () => {
  it('starts at 0, ends at 1 and never moves backwards within a round', () => {
    const evs = events({}, { templateIds: ['ig-post'] });
    let v = emptyJobView();
    expect(jobProgress(v)).toBe(0);
    let last = 0;
    for (const e of evs) {
      v = reduceJob(v, e);
      if (v.stage === 'rewriting' || v.round === 2) break;
      const p = jobProgress(v);
      expect(p).toBeGreaterThanOrEqual(last);
      last = p;
    }
    expect(last).toBeGreaterThan(0.9);
    expect(jobProgress(applyEvents(evs))).toBe(1);
  });

  it('moves through the rendering range as ComfyUI steps arrive', () => {
    const evs = events({}, { templateIds: ['ig-post'] });
    const firstGenerate = evs.findIndex((e) => e.type === 'render.progress' && e.node === 'generate');
    const p = jobProgress(applyEvents(evs.slice(0, firstGenerate + 1)));
    expect(p).toBeGreaterThan(0.2);
    expect(p).toBeLessThan(0.7);
  });
});

describe('withLiveStage', () => {
  // 任務列表是讀取當下的快照：job_a 讀取時還在 ComfyUI 生成
  const viewing: JobSummary = { ...makeJobSnapshot({ jobId: 'job_a' }).summary, stage: 'rendering', round: 1, finished: false };
  const other = makeJobSnapshot({ jobId: 'job_b' }).summary;

  it.each([
    ['reviewing', 1, false],
    ['done', 2, true],
    ['needs_review', 3, true],
    ['cancelled', 1, true],
  ] as const)('uses the stream for the job being viewed (%s)', (stage, round, finished) => {
    const view = reduceJob(emptyJobView('job_a'), { type: 'job.status', stage, round });
    const [a, b] = withLiveStage([viewing, other], view);
    expect(a).toMatchObject({ id: 'job_a', stage, round, finished });
    expect(b).toBe(other);
  });

  it('keeps the snapshot until the stream has an event', () => {
    const jobs = [viewing, other];
    expect(withLiveStage(jobs, emptyJobView('job_a'))).toEqual(jobs);
  });
});
