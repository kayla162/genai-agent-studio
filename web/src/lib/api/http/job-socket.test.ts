import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobMessage } from '@/types/contract';
import { HttpApiClient } from './client';

/** 測試用 WebSocket：由測試扮演伺服器（open、send、drop） */
class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.();
  }

  send(message: Partial<JobMessage> & { seq: number }) {
    this.onmessage?.({ data: JSON.stringify({ type: 'log', source: 'api', level: 'info', message: '', ts: '', ...message }) });
  }

  drop(code: number) {
    this.onclose?.({ code });
  }
}

const sockets = () => FakeSocket.all;
const last = () => FakeSocket.all.at(-1)!;
const done = (seq: number) => ({ type: 'job.status' as const, stage: 'done' as const, round: 1, seq });

function client() {
  return new HttpApiClient({
    baseUrl: 'http://api.test',
    fetch: vi.fn(async () => Response.json({ status: 'ok' })),
    WebSocket: FakeSocket as unknown as typeof WebSocket,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
});
afterEach(() => vi.useRealTimers());

describe('HttpApiClient.subscribe', () => {
  it('replays and streams events, then stops when the server closes after the final event', async () => {
    const api = client();
    const seqs: number[] = [];
    api.subscribe('job_1', (m) => seqs.push(m.seq));
    expect(last().url).toBe('ws://api.test/ws/jobs/job_1?after=0');
    last().open();
    expect(api.connection.get().status).toBe('connected');
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    last().send(done(3));
    last().drop(1000);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(seqs).toEqual([1, 2, 3]);
    expect(sockets()).toHaveLength(1);
  });

  it('reconnects after the last seq with a growing delay and skips repeated events', async () => {
    const api = client();
    const seqs: number[] = [];
    api.subscribe('job_1', (m) => seqs.push(m.seq));
    last().open();
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    last().drop(1006);
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '任務事件的連線中斷，1 秒後重新連線' });
    await vi.advanceTimersByTimeAsync(999);
    expect(sockets()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(last().url).toBe('ws://api.test/ws/jobs/job_1?after=2');
    // 還沒連上就又斷了：等待時間加倍
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(sockets()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(sockets()).toHaveLength(3);
    last().open();
    last().send({ seq: 2 });
    last().send({ seq: 3 });
    expect(seqs).toEqual([1, 2, 3]);
    expect(api.connection.get().status).toBe('connected');
  });

  it('keeps growing the delay, up to 10 seconds, while connections open but close before any message', async () => {
    const api = client();
    api.subscribe('job_1', () => {});
    // 伺服器先 accept、再因 Redis 連不上而以 1011 關閉：每次都「連上」了，但沒有送出任何事件
    for (const wait of [1_000, 2_000, 4_000, 8_000, 10_000, 10_000]) {
      const before = sockets().length;
      last().open();
      last().drop(1011);
      expect(api.connection.get().error).toBe(`任務事件的連線中斷，${wait / 1000} 秒後重新連線`);
      await vi.advanceTimersByTimeAsync(wait - 1);
      expect(sockets()).toHaveLength(before);
      await vi.advanceTimersByTimeAsync(1);
      expect(sockets()).toHaveLength(before + 1);
    }
  });

  it('resets the delay to 1 second once a connection delivers a message', async () => {
    const api = client();
    api.subscribe('job_1', () => {});
    for (const wait of [1_000, 2_000]) {
      last().open();
      last().drop(1011);
      await vi.advanceTimersByTimeAsync(wait);
    }
    // 這次連線送出了事件，所以下一次中斷從 1 秒重新計算
    last().open();
    last().send({ seq: 1 });
    last().drop(1006);
    expect(api.connection.get().error).toBe('任務事件的連線中斷，1 秒後重新連線');
    await vi.advanceTimersByTimeAsync(999);
    expect(sockets()).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(sockets()).toHaveLength(4);
    // 之後又回到沒有事件的中斷：等待時間再從 2 秒開始加倍
    last().open();
    last().drop(1011);
    expect(api.connection.get().error).toBe('任務事件的連線中斷，2 秒後重新連線');
  });

  it('reports an unknown job once and does not reconnect', async () => {
    const onError = vi.fn();
    client().subscribe('job_nope', () => {}, onError);
    last().drop(4404);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toBe('找不到任務：job_nope');
    expect(sockets()).toHaveLength(1);
  });

  it('stops delivering events and cancels a pending reconnect once unsubscribed', async () => {
    const api = client();
    const seqs: number[] = [];
    const stop = api.subscribe('job_1', (m) => seqs.push(m.seq));
    last().open();
    last().send({ seq: 1 });
    last().drop(1006);
    stop();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(sockets()).toHaveLength(1);

    const stopAgain = api.subscribe('job_2', (m) => seqs.push(m.seq));
    last().open();
    stopAgain();
    expect(last().closed).toBe(true);
    last().send({ seq: 1 });
    expect(seqs).toEqual([1]);
  });

  it('keeps streaming when a subscriber throws', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const seqs: number[] = [];
    client().subscribe('job_1', (m) => {
      seqs.push(m.seq);
      if (m.seq === 1) throw new Error('boom');
    });
    last().open();
    last().send({ seq: 1 });
    last().send({ seq: 2 });
    expect(seqs).toEqual([1, 2]);
    expect(error).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
