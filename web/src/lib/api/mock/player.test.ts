import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent } from '@/types/contract';
import { playTimeline } from './player';
import type { TimedEvent } from './scenario';

const ev = (n: number): JobEvent => ({ type: 'log', source: 'api', level: 'info', message: String(n) });
const TIMELINE: TimedEvent[] = [
  { at: 0, event: ev(0) }, { at: 100, event: ev(1) }, { at: 100, event: ev(2) }, { at: 300, event: ev(3) },
];

function collect(speed: number) {
  const got: string[] = [];
  const state = { done: false };
  const handle = playTimeline(TIMELINE, {
    getSpeed: () => speed,
    onEvent: (e) => got.push(e.type === 'log' ? e.message : e.type),
    onDone: () => { state.done = true; },
  });
  return { got, state, handle };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('playTimeline', () => {
  it('emits events at their timestamps, grouping events at the same time', async () => {
    const { got, state } = collect(1);
    expect(got).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(got).toEqual(['0']);
    await vi.advanceTimersByTimeAsync(100);
    expect(got).toEqual(['0', '1', '2']);
    await vi.advanceTimersByTimeAsync(199);
    expect(got).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(got).toEqual(['0', '1', '2', '3']);
    expect(state.done).toBe(true);
  });

  it('divides waiting time by the speed', async () => {
    const { got } = collect(2);
    await vi.advanceTimersByTimeAsync(150);
    expect(got).toEqual(['0', '1', '2', '3']);
  });

  it('stops after cancel', async () => {
    const { got, state, handle } = collect(1);
    await vi.advanceTimersByTimeAsync(0);
    handle.cancel();
    await vi.advanceTimersByTimeAsync(1000);
    expect(got).toEqual(['0']);
    expect(state.done).toBe(false);
  });
});
