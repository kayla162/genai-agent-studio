import type { CheckStatus, JobEvent } from '@/types/contract';
import { truncate } from '@/lib/core/text';
import { STAGE_LABEL } from '@/lib/jobs/view';
import { seedOf } from './prompt';

/** 事件串流的分類（篩選用） */
export type EventGroup = 'job' | 'agent' | 'rag' | 'comfy' | 'review' | 'log';
export const EVENT_GROUPS: { id: EventGroup; label: string }[] = [
  { id: 'job', label: '任務' },
  { id: 'agent', label: 'Agent' },
  { id: 'rag', label: 'RAG' },
  { id: 'comfy', label: 'ComfyUI' },
  { id: 'review', label: '審查' },
  { id: 'log', label: 'Log' },
];

export function eventGroup(e: JobEvent): EventGroup {
  switch (e.type) {
    case 'job.accepted':
    case 'job.status':
    case 'job.completed':
    case 'job.needs_review':
    case 'job.failed':
      return 'job';
    case 'brief.parsed':
    case 'prompt.generated':
    case 'rewrite.started':
      return 'agent';
    case 'rag.retrieved':
    case 'rag.reranked':
      return 'rag';
    case 'comfy.queued':
    case 'render.progress':
    case 'render.completed':
      return 'comfy';
    case 'review.check':
    case 'review.completed':
      return 'review';
    case 'log':
      return 'log';
  }
}

/** render id 去掉任務 id：job_…_r1_ig-post_v0 → r1_ig-post_v0 */
export function shortRenderId(renderId: string): string {
  return renderId.match(/_(r\d+_[a-z-]+_v\d+)$/)?.[1] ?? renderId;
}

const MARK: Record<CheckStatus, string> = { pass: '✓', warn: '⚠', fail: '✗' };

/** 事件串流每一列的摘要（事件類型另外顯示） */
export function describeEvent(e: JobEvent): string {
  switch (e.type) {
    case 'job.accepted':
      return e.jobId;
    case 'job.status':
      return e.round ? `${STAGE_LABEL[e.stage]}・第 ${e.round} 輪` : STAGE_LABEL[e.stage];
    case 'brief.parsed': {
      const b = e.parsedBrief;
      return `語氣 ${b.tone}・賣點 ${b.sellingPoints.length} 項・檔期 ${b.campaign ?? '無'}・優惠 ${b.offer ?? '無'}`;
    }
    case 'rag.retrieved':
      return `召回 ${e.hits.length} 筆：${truncate(e.query, 36)}`;
    case 'rag.reranked':
      return e.hits.map((h) => `${h.tag} ${(h.rerankScore ?? 0).toFixed(2)}`).join(' > ');
    case 'prompt.generated':
      return `第 ${e.round} 輪 ${e.templateId}：${e.spec.layout.length} 個 BBox・seed ${seedOf(e.spec)}`;
    case 'comfy.queued':
      return `${e.injection.workflowFile}・注入 ${e.injection.params.length} 個參數`;
    case 'render.progress':
      return `${e.node} ${e.step}/${e.maxStep}`;
    case 'render.completed':
      return `第 ${e.round} 輪 ${e.renders.length} 張候選`;
    case 'review.check':
      return `${shortRenderId(e.renderId)}・${MARK[e.check.status]} ${e.check.name}：${e.check.value}`;
    case 'review.completed':
      return `${shortRenderId(e.renderId)}・${e.score} 分・${e.passed ? '通過' : '未通過'}`;
    case 'rewrite.started':
      return `${e.templateId} 未通過（${e.reasons.join(', ')}）→ ${e.fixes.map((f) => f.title).join('、')}${e.requery ? '・重新檢索' : ''}`;
    case 'job.completed':
      return `最佳候選 ${Object.keys(e.bestRenderIds).length} 張`;
    case 'job.needs_review':
    case 'job.failed':
      return e.reason;
    case 'log':
      return `[${e.source.toUpperCase()}] ${e.message}`;
  }
}

/** 相對於任務開始的時間：+1.25s */
export function formatOffset(ms: number): string {
  return `+${(ms / 1000).toFixed(2)}s`;
}

/** 耗時：850 ms、14.5 秒、2 分 05 秒 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} 秒`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)} 分 ${String(s % 60).padStart(2, '0')} 秒`;
}
