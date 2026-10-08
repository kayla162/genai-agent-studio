import { describe, expect, it } from 'vitest';
import type { JobMessage } from '@/types/contract';
import { makeJobSnapshot } from '@/test/fixtures';
import { FLOW_NODES, flowState } from './flow';

const statuses = (messages: JobMessage[]) => {
  const { nodes } = flowState(messages);
  return Object.fromEntries(FLOW_NODES.map((n) => [n.id, nodes[n.id].status]));
};

describe('flowState', () => {
  it('lists the eight nodes from the spec in order', () => {
    expect(FLOW_NODES.map((n) => n.step)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('marks every node done after a retried job, with the review node warned', () => {
    const { events } = makeJobSnapshot();
    expect(statuses(events)).toEqual({
      orchestrator: 'done', brief: 'done', rag: 'done', prompt: 'done', comfy: 'done', compose: 'done', review: 'warn', save: 'done',
    });
    const flow = flowState(events);
    expect(flow.loop).toEqual({ count: 1, requery: true, active: false, ms: 800 });
    expect(flow.elapsedMs).toBe(14_500);
  });

  it('counts visits and time spent in each node from the timestamps', () => {
    const { nodes } = flowState(makeJobSnapshot().events);
    expect(Object.fromEntries(FLOW_NODES.map((n) => [n.id, [nodes[n.id].visits, nodes[n.id].ms]]))).toEqual({
      orchestrator: [1, 14_500],
      brief: [1, 1_100],
      rag: [1, 1_200],
      prompt: [2, 1_600],
      comfy: [2, 6_400],
      compose: [2, 600],
      review: [2, 2_400],
      save: [1, 400],
    });
  });

  it('shows the current node as active while the job runs', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    expect(statuses(events.slice(0, rendering + 3))).toEqual({
      orchestrator: 'active', brief: 'done', rag: 'done', prompt: 'done', comfy: 'active', compose: 'idle', review: 'idle', save: 'idle',
    });
    const rewriting = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rewriting');
    expect(flowState(events.slice(0, rewriting + 1)).loop.active).toBe(true);
  });

  it('marks the review node as an error when the job needs manual review', () => {
    const { events } = makeJobSnapshot({ demo: { forceAllFail: true } });
    expect(statuses(events).review).toBe('error');
    expect(flowState(events).loop.count).toBe(2);
  });

  it('marks the node that was running when the job was cancelled', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    const head = events.slice(0, rendering + 3);
    const cancelled: JobMessage = { type: 'job.status', stage: 'cancelled', round: 1, seq: head.length + 1, ts: head.at(-1)!.ts };
    const s = statuses([...head, cancelled]);
    expect(s.comfy).toBe('error');
    expect(s.orchestrator).toBe('error');
  });

  it('marks the node that was running when the job failed', () => {
    const { events } = makeJobSnapshot();
    const rendering = events.findIndex((e) => e.type === 'job.status' && e.stage === 'rendering');
    const head = events.slice(0, rendering + 3);
    const ts = head.at(-1)!.ts;
    const tail: JobMessage[] = [
      { type: 'job.failed', jobId: 'job_fixture', reason: 'ComfyUI 沒有回應', seq: head.length + 1, ts },
      { type: 'job.status', stage: 'failed', round: 1, seq: head.length + 2, ts },
    ];
    const s = statuses([...head, ...tail]);
    expect(s.comfy).toBe('error');
    expect(s.orchestrator).toBe('error');
  });

  it('keeps only the orchestrator active while the job is queued', () => {
    const queued: JobMessage[] = [
      { type: 'job.accepted', jobId: 'j', seq: 1, ts: '2026-10-07T01:00:00.000Z' },
      { type: 'job.status', stage: 'queued', round: 0, seq: 2, ts: '2026-10-07T01:00:00.000Z' },
    ];
    expect(statuses(queued)).toEqual({
      orchestrator: 'active', brief: 'idle', rag: 'idle', prompt: 'idle', comfy: 'idle', compose: 'idle', review: 'idle', save: 'idle',
    });
  });

  it('is idle without messages', () => {
    const flow = flowState([]);
    expect(Object.values(flow.nodes).every((n) => n.status === 'idle' && n.visits === 0)).toBe(true);
    expect(flow.elapsedMs).toBe(0);
  });
});
