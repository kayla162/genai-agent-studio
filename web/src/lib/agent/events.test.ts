import { describe, expect, it } from 'vitest';
import type { JobEvent } from '@/types/contract';
import { makeJobSnapshot } from '@/test/fixtures';
import { describeEvent, eventGroup, formatDuration, formatOffset, shortRenderId } from './events';

const { events } = makeJobSnapshot();
const pick = (pred: (e: JobEvent) => boolean): JobEvent => {
  const e = events.find(pred);
  if (!e) throw new Error('missing event');
  return e;
};

describe('eventGroup', () => {
  it('groups every event type of a job', () => {
    const groups = Object.fromEntries(events.map((e) => [e.type, eventGroup(e)]));
    expect(groups).toEqual({
      'job.accepted': 'job', 'job.status': 'job', 'job.completed': 'job', log: 'log', 'brief.parsed': 'agent',
      'rag.retrieved': 'rag', 'rag.reranked': 'rag', 'prompt.generated': 'agent', 'comfy.queued': 'comfy',
      'render.progress': 'comfy', 'render.completed': 'comfy', 'review.check': 'review', 'review.completed': 'review',
      'rewrite.started': 'agent',
    });
    expect(eventGroup({ type: 'job.needs_review', jobId: 'j', reason: 'x' })).toBe('job');
    expect(eventGroup({ type: 'job.failed', jobId: 'j', reason: 'x' })).toBe('job');
  });
});

describe('describeEvent', () => {
  it('summarises status, review and rewrite events', () => {
    expect(describeEvent({ type: 'job.status', stage: 'parsing', round: 0 })).toBe('需求拆解');
    expect(describeEvent({ type: 'job.status', stage: 'reviewing', round: 2 })).toBe('合規審查・第 2 輪');
    expect(describeEvent({ type: 'job.status', stage: 'queued', round: 0 })).toBe('排隊中');
    expect(describeEvent({ type: 'job.failed', jobId: 'j', reason: 'ComfyUI 沒有回應' })).toBe('ComfyUI 沒有回應');
    expect(describeEvent(pick((e) => e.type === 'review.check' && e.check.id === 'banned_words' && e.round === 1)))
      .toBe('r1_ig-post_v0・✗ 禁用詞檢查：禁用詞「根治」「醫療級」');
    expect(describeEvent(pick((e) => e.type === 'rewrite.started'))).toBe(
      'ig-post 未通過（banned_words, color_delta, logo_clearance, disclaimer, vlm_exaggeration, vlm_occlusion）→ 文案改寫、色彩修正、版面修正、補充註記、構圖修正・重新檢索',
    );
    expect(describeEvent(pick((e) => e.type === 'rag.reranked'))).toBe('color 0.97 > law 0.93 > logo 0.88 > layout 0.74 > history 0.61');
    expect(describeEvent({ type: 'log', source: 'vlm', level: 'warn', message: '第 1 輪：0/1 個模板通過' }))
      .toBe('[VLM] 第 1 輪：0/1 個模板通過');
  });
});

describe('formatting', () => {
  it('shortens render ids', () => {
    expect(shortRenderId('job_20261005_0930_7fff_r2_ecom-main_v3')).toBe('r2_ecom-main_v3');
    expect(shortRenderId('other')).toBe('other');
  });

  it('formats offsets and durations', () => {
    expect(formatOffset(1_250)).toBe('+1.25s');
    expect(formatDuration(850)).toBe('850 ms');
    expect(formatDuration(14_500)).toBe('14.5 秒');
    expect(formatDuration(125_000)).toBe('2 分 05 秒');
  });
});
