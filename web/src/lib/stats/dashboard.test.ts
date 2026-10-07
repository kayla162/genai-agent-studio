import { describe, expect, it } from 'vitest';
import { makeJobSnapshot } from '@/test/fixtures';
import { dashboardStats, jobCost, jobStat, rerankHitCurve, UNIT_COST_USD } from './dashboard';

const retried = makeJobSnapshot({ jobId: 'job_a', createdAt: '2026-10-01T01:00:00.000Z' });
const firstPass = makeJobSnapshot({ jobId: 'job_b', createdAt: '2026-10-02T01:00:00.000Z', demo: { firstRoundFail: false } });
const failed = makeJobSnapshot({ jobId: 'job_c', createdAt: '2026-10-03T01:00:00.000Z', demo: { forceAllFail: true } });

describe('jobCost', () => {
  it('adds LLM calls, rerank, image generation and VLM review', () => {
    // 需求拆解 1 + Prompt 2 輪 + Query Rewriting 1 = 4 次 LLM；2 輪 × 4 張候選
    const expected = 4 * UNIT_COST_USD.llmCall + UNIT_COST_USD.rerank + 8 * UNIT_COST_USD.comfyImage + 8 * UNIT_COST_USD.vlmReview;
    expect(jobCost(retried)).toBeCloseTo(expected, 10);
  });

  it('prices Ideogram images by the API rate', () => {
    const ideogram = makeJobSnapshot({ engine: 'ideogram' });
    expect(jobCost(ideogram) - jobCost(retried)).toBeCloseTo(8 * (UNIT_COST_USD.ideogramImage - UNIT_COST_USD.comfyImage), 10);
  });
});

describe('jobStat', () => {
  it('summarises a finished job from its events', () => {
    expect(jobStat(retried)).toEqual({
      jobId: 'job_a', brandId: 'selune', createdAt: '2026-10-01T01:00:00.000Z', outcome: 'done', templates: 1, rounds: 2,
      renders: 8, delivered: 1, durationMs: 14_500, costUsd: jobCost(retried),
    });
    expect(jobStat(failed)).toMatchObject({ outcome: 'needs_review', rounds: 3, renders: 12, delivered: 0, durationMs: 20_800 });
  });

  it('skips running and cancelled jobs', () => {
    expect(jobStat(makeJobSnapshot({ upTo: 20 }))).toBeNull();
    const cancelled = makeJobSnapshot();
    cancelled.summary.stage = 'cancelled';
    expect(jobStat(cancelled)).toBeNull();
  });
});

describe('rerankHitCurve', () => {
  it('shows rerank bringing the cited guidelines to the top', () => {
    // 第一輪的問題引用了色彩、法規、Logo 三段規範：向量順序是 layout > color > history > logo > law
    expect(rerankHitCurve(retried.events)).toEqual({
      vector: [0, 1 / 3, 1 / 3, 2 / 3, 1],
      rerank: [1 / 3, 2 / 3, 1, 1, 1],
    });
  });

  it('returns null when no failed or warned check cites a retrieved guideline', () => {
    const passOnly = retried.events.filter((e) => e.type !== 'review.check' || e.check.status === 'pass');
    expect(rerankHitCurve(passOnly)).toBeNull();
  });
});

describe('dashboardStats', () => {
  const stats = dashboardStats([retried, firstPass, failed, makeJobSnapshot({ jobId: 'job_running', upTo: 30 })]);

  it('counts only finished jobs', () => {
    expect(stats.jobs).toBe(3);
    expect(stats.renders).toBe(8 + 4 + 12);
  });

  it('computes pass rate, first-round pass rate, retries and duration', () => {
    expect(stats.passRate).toBeCloseTo(2 / 3, 10);
    expect(stats.firstPassRate).toBeCloseTo(1 / 3, 10);
    expect(stats.avgRetries).toBe(1);
    expect(stats.avgDurationMs).toBe((14_500 + 8_200 + 20_800) / 3);
  });

  it('spreads the cost of every job over the delivered images', () => {
    const total = jobCost(retried) + jobCost(firstPass) + jobCost(failed);
    expect(stats.costPerImage).toBeCloseTo(total / 2, 10);
  });

  it('counts failures and warnings per check in the standard order', () => {
    expect(stats.checkFailures.map((c) => c.checkId)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
      'vlm_exaggeration', 'vlm_occlusion', 'vlm_quality',
    ]);
    // 有瑕疵的輪次：retried 第 1 輪 4 張 + failed 3 輪 12 張
    expect(stats.checkFailures[0]).toEqual({ checkId: 'banned_words', name: '禁用詞檢查', kind: 'rule', fail: 16, warn: 0 });
    expect(stats.checkFailures.find((c) => c.checkId === 'disclaimer')).toMatchObject({ fail: 0, warn: 16 });
  });

  it('averages the rerank hit curves', () => {
    expect(stats.rerankHits).toHaveLength(5);
    const k3 = stats.rerankHits[2];
    expect(k3.k).toBe(3);
    expect(k3.rerank).toBe(1);
    expect(k3.vector).toBeLessThan(0.5);
  });

  it('lists recent jobs newest first', () => {
    expect(stats.recent.map((j) => j.jobId)).toEqual(['job_c', 'job_b', 'job_a']);
  });

  it('returns zeros for no data', () => {
    expect(dashboardStats([])).toEqual({
      jobs: 0, renders: 0, passRate: 0, firstPassRate: 0, avgRetries: 0, avgDurationMs: 0, costPerImage: null,
      checkFailures: [], rerankHits: [], recent: [],
    });
  });
});
