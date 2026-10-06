import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getApiClient } from '@/lib/api';
import { useQueueStore } from './queue';

const q = () => useQueueStore.getState();
const statuses = () => q().items.map((i) => i.status);
const BATCH = {
  brandId: 'selune', brief: '週年慶主打買一送一', templateIds: ['ig-post' as const], variants: 2,
  products: [{ id: 'prod_selune_serum', name: '精華液' }, { id: 'prod_selune_serum', name: '精華液（第二筆）' }],
};

beforeEach(() => {
  vi.useFakeTimers();
  // 4× 速度：含一次重試的任務約 3.6 秒
  getApiClient().demo?.set({ speed: 4, firstRoundFail: true, forceAllFail: false });
  useQueueStore.setState({ items: [], paused: false });
});
afterEach(() => vi.useRealTimers());

describe('queue store', () => {
  it('runs one item at a time, in order', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['running', 'pending']);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(statuses()).toEqual(['done', 'running']);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(statuses()).toEqual(['done', 'done']);
    expect(q().items[0].view!.bestRenderIds['ig-post']).toBeDefined();
  });

  it('pausing lets the running item finish but does not start the next', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(100);
    q().togglePause();
    await vi.advanceTimersByTimeAsync(8_000);
    expect(statuses()).toEqual(['done', 'pending']);
    q().togglePause();
    await vi.advanceTimersByTimeAsync(3_800);
    expect(statuses()).toEqual(['done', 'done']);
  });

  it('skips held items until they are released', async () => {
    q().enqueue(BATCH);
    q().hold(q().items[1].id);
    await vi.advanceTimersByTimeAsync(8_000);
    expect(statuses()).toEqual(['done', 'held']);
    q().release(q().items[1].id);
    await vi.advanceTimersByTimeAsync(3_800);
    expect(statuses()).toEqual(['done', 'done']);
  });

  it('cancels running and waiting items, then clears finished ones', async () => {
    q().enqueue(BATCH);
    await vi.advanceTimersByTimeAsync(500);
    await q().cancel(q().items[1].id);
    await q().cancel(q().items[0].id);
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['cancelled', 'cancelled']);
    q().clearFinished();
    expect(q().items).toEqual([]);
  });

  it('marks an item as failed when the job cannot be created', async () => {
    q().enqueue({ ...BATCH, products: [{ id: 'nope', name: '不存在' }] });
    await vi.advanceTimersByTimeAsync(100);
    expect(statuses()).toEqual(['error']);
    expect(q().items[0].error).toContain('Unknown product');
  });
});
