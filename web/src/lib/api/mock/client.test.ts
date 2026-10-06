import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput } from '@/types/contract';
import { getApiClient } from '../index';
import { MockApiClient, makeJobId } from './client';

const BRIEF = '週年慶主打買一送一，溫柔療癒';
const NOW = new Date(2026, 9, 5, 9, 30);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => vi.useRealTimers());

async function startJob(api: MockApiClient, over: Partial<JobInput> = {}) {
  const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
  const { jobId } = await api.createJob({
    brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
    variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2,
    ...over,
  });
  const events: JobEvent[] = [];
  api.subscribe(jobId, (e) => events.push(e));
  return { jobId, events };
}

const statuses = (events: JobEvent[]) => events.flatMap((e) => (e.type === 'job.status' ? [e.stage] : []));

describe('makeJobId', () => {
  it('formats the local date, time and a 4-hex suffix', () => {
    expect(makeJobId(NOW, () => 0.5)).toBe('job_20261005_0930_7fff');
  });
});

describe('products', () => {
  it('lists samples per brand, saves and deletes custom products', async () => {
    const api = new MockApiClient();
    expect((await api.listProducts('selune')).map((p) => p.id)).toEqual(['prod_selune_serum']);
    const saved = await api.saveProduct({
      brandId: 'selune', name: '晚安面膜', features: ['保濕'], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'blob:test' },
    });
    expect(saved.id).toMatch(/^prod_/);
    expect(saved.createdAt).toBe(NOW.toISOString());
    expect((await api.listProducts('selune')).map((p) => p.name)).toEqual(['極光玻尿酸修護精華 30ml', '晚安面膜']);
    await api.deleteProduct(saved.id);
    await api.deleteProduct('prod_selune_serum');
    expect(await api.listProducts('selune')).toEqual([]);
    expect(await api.listProducts('misty-isle')).toHaveLength(1);
  });
});

describe('jobs', () => {
  it('runs the default demo to completion and replays events to late subscribers', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    expect(statuses(events).at(-1)).toBe('done');
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
    const late: JobEvent[] = [];
    api.subscribe(jobId, (e) => late.push(e));
    expect(late).toEqual(events);
  });

  it('respects the demo speed', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const { events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
  });

  it('can be cancelled', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(1_000);
    await api.cancelJob(jobId);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.at(-1)).toEqual({ type: 'job.status', stage: 'cancelled', round: 0 });
    expect(events.some((e) => e.type === 'job.completed')).toBe(false);
  });

  it('saves the selected render with edited copy to history', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');

    const copy = { ...prompt.spec.copy, price: { ...prompt.spec.copy.price, sale: 999 } };
    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, copy);
    expect(entry).toMatchObject({ jobId, brandId: 'selune', templateId: 'ig-post', favorite: false, writtenToRag: true });
    expect(entry.render.passed).toBe(true);
    expect(entry.render.checks).toHaveLength(10);
    expect(entry.copy.price.sale).toBe(999);
    expect(await api.listHistory('selune')).toHaveLength(1);
    expect(await api.listHistory('misty-isle')).toHaveLength(0);
  });

  it('rejects unknown jobs and empty template lists', async () => {
    const api = new MockApiClient();
    expect(() => api.subscribe('nope', () => {})).toThrow('Unknown job');
    await expect(startJob(api, { templateIds: [] })).rejects.toThrow('至少要選一個通路模板');
  });

  it('keeps every history entry when selections run concurrently', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api, { templateIds: ['ig-post', 'story'] });
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    await Promise.all([
      api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy),
      api.selectRender(jobId, done.bestRenderIds.story!, prompt.spec.copy),
    ]);
    expect((await api.listHistory('selune')).map((h) => h.templateId).sort()).toEqual(['ig-post', 'story']);
  });

  it('keeps every product when saves run concurrently', async () => {
    const api = new MockApiClient();
    const draft = (name: string) => ({
      brandId: 'selune', name, features: [], price: { sale: 1, original: 1 }, photo: { source: 'upload' as const, url: 'blob:x' },
    });
    await Promise.all([api.saveProduct(draft('A')), api.saveProduct(draft('B'))]);
    expect((await api.listProducts('selune')).map((p) => p.name)).toEqual(['極光玻尿酸修護精華 30ml', 'A', 'B']);
  });

  it('keeps delivering to other subscribers when one throws', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const api = new MockApiClient();
    const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
    const { jobId } = await api.createJob({
      brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
      variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2,
    });
    api.subscribe(jobId, () => { throw new Error('boom'); });
    const events: JobEvent[] = [];
    api.subscribe(jobId, (e) => events.push(e));
    await vi.advanceTimersByTimeAsync(14_500);
    expect(statuses(events).at(-1)).toBe('done');
    expect(error).toHaveBeenCalled();
    error.mockRestore();
  });
});

describe('getApiClient', () => {
  it('returns a singleton mock client with demo controls by default', () => {
    const api = getApiClient();
    expect(api).toBe(getApiClient());
    expect(api.demo?.get()).toEqual({ speed: 1, firstRoundFail: true, forceAllFail: false });
  });
});
