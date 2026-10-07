import type { CheckFailureStat, CheckId, DashboardStats, JobMessage, JobStat, RerankHitStat } from '@/types/contract';
import { CHECK_IDS } from '@/types/contract';
import type { JobSnapshot } from '@/lib/api/client';

/** 估算單價（美元）。第二階段改由後端回報實際用量。 */
export const UNIT_COST_USD = {
  /** LLM 呼叫一次：需求拆解、每個模板每輪的 Prompt 構建、Query Rewriting（約 2k tokens） */
  llmCall: 0.0006,
  /** BGE Reranker 一次（自架 GPU） */
  rerank: 0.0002,
  /** ComfyUI 生成 1 張 2K 候選（雲端 GPU 約 4 秒） */
  comfyImage: 0.0042,
  /** Ideogram 4.0 API 生成 1 張 */
  ideogramImage: 0.06,
  /** VLM 審查 1 張 */
  vlmReview: 0.0011,
} as const;

const RECENT = 8;

const count = (events: JobMessage[], type: JobMessage['type']) => events.filter((e) => e.type === type).length;

function renderCount(events: JobMessage[]): number {
  return events.reduce((n, e) => n + (e.type === 'render.completed' ? e.renders.length : 0), 0);
}

/** 依事件估算一個任務的成本（美元） */
export function jobCost({ summary, events }: JobSnapshot): number {
  const image = summary.input.engine === 'ideogram' ? UNIT_COST_USD.ideogramImage : UNIT_COST_USD.comfyImage;
  const llmCalls = count(events, 'brief.parsed') + count(events, 'prompt.generated') + count(events, 'rewrite.started');
  return (
    UNIT_COST_USD.llmCall * llmCalls
    + UNIT_COST_USD.rerank * count(events, 'rag.reranked')
    + image * renderCount(events)
    + UNIT_COST_USD.vlmReview * count(events, 'review.completed')
  );
}

/** 已結束（完成或需人工審核）的任務才有統計；執行中與已取消的回傳 null */
export function jobStat(snap: JobSnapshot): JobStat | null {
  const { summary, events } = snap;
  if (!summary.finished || (summary.stage !== 'done' && summary.stage !== 'needs_review')) return null;
  const first = events[0];
  const last = events.at(-1);
  return {
    jobId: summary.id,
    brandId: summary.input.brandId,
    createdAt: summary.createdAt,
    outcome: summary.stage,
    templates: summary.input.templateIds.length,
    rounds: summary.round,
    renders: renderCount(events),
    delivered: Object.keys(summary.bestRenderIds).length,
    durationMs: first && last ? Date.parse(last.ts) - Date.parse(first.ts) : 0,
    costUsd: jobCost(snap),
  };
}

/** 第一輪就有候選通過審查的模板數 */
function firstRoundPassed(events: JobMessage[]): number {
  const templateOf = new Map<string, string>();
  const passed = new Set<string>();
  for (const e of events) {
    if (e.type === 'render.completed' && e.round === 1) for (const r of e.renders) templateOf.set(r.id, r.templateId);
    if (e.type === 'review.completed' && e.round === 1 && e.passed) {
      const t = templateOf.get(e.renderId);
      if (t) passed.add(t);
    }
  }
  return passed.size;
}

/** 前 k 筆（k = 1…n）涵蓋審查未通過項目所引用規範的比例；沒有可比較的引用時回傳 null */
export function rerankHitCurve(events: JobMessage[]): { vector: number[]; rerank: number[] } | null {
  const retrieved = events.find((e) => e.type === 'rag.retrieved');
  const reranked = events.find((e) => e.type === 'rag.reranked');
  if (retrieved?.type !== 'rag.retrieved' || reranked?.type !== 'rag.reranked') return null;
  const vectorOrder = [...retrieved.hits].sort((a, b) => b.vectorScore - a.vectorScore).map((h) => h.chunkId);
  const rerankOrder = reranked.hits.map((h) => h.chunkId);
  const cited = new Set(events.flatMap((e) =>
    e.type === 'review.check' && e.check.status !== 'pass' && e.check.ragRef ? [e.check.ragRef] : []));
  const relevant = vectorOrder.filter((id) => cited.has(id));
  if (!relevant.length) return null;
  const curve = (order: string[]) =>
    order.map((_, i) => relevant.filter((id) => order.slice(0, i + 1).includes(id)).length / relevant.length);
  return { vector: curve(vectorOrder), rerank: curve(rerankOrder) };
}

function checkFailures(snaps: JobSnapshot[]): CheckFailureStat[] {
  const stats = new Map<CheckId, CheckFailureStat>();
  for (const { events } of snaps) {
    for (const e of events) {
      if (e.type !== 'review.check') continue;
      const c = e.check;
      const s = stats.get(c.id) ?? { checkId: c.id, name: c.name, kind: c.kind, fail: 0, warn: 0 };
      if (c.status === 'fail') s.fail++;
      if (c.status === 'warn') s.warn++;
      stats.set(c.id, s);
    }
  }
  return CHECK_IDS.flatMap((id) => stats.get(id) ?? []);
}

function rerankHits(snaps: JobSnapshot[]): RerankHitStat[] {
  const curves = snaps.map((s) => rerankHitCurve(s.events)).filter((c) => c !== null);
  if (!curves.length) return [];
  const n = Math.min(...curves.map((c) => c.vector.length));
  const avg = (pick: (c: { vector: number[]; rerank: number[] }) => number) =>
    curves.reduce((sum, c) => sum + pick(c), 0) / curves.length;
  return Array.from({ length: n }, (_, i) => ({ k: i + 1, vector: avg((c) => c.vector[i]), rerank: avg((c) => c.rerank[i]) }));
}

const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0);

/** 成效儀表板：只統計已結束（完成或需人工審核）的任務 */
export function dashboardStats(snaps: JobSnapshot[]): DashboardStats {
  const finished = snaps.flatMap((snap) => {
    const stat = jobStat(snap);
    return stat ? [{ snap, stat }] : [];
  });
  const stats = finished.map((x) => x.stat);
  const templates = stats.reduce((n, s) => n + s.templates, 0);
  const delivered = stats.reduce((n, s) => n + s.delivered, 0);
  const cost = stats.reduce((n, s) => n + s.costUsd, 0);
  const finishedSnaps = finished.map((x) => x.snap);
  return {
    jobs: stats.length,
    renders: stats.reduce((n, s) => n + s.renders, 0),
    passRate: stats.length ? stats.filter((s) => s.outcome === 'done').length / stats.length : 0,
    firstPassRate: templates ? finishedSnaps.reduce((n, s) => n + firstRoundPassed(s.events), 0) / templates : 0,
    avgRetries: mean(stats.map((s) => s.rounds - 1)),
    avgDurationMs: mean(stats.map((s) => s.durationMs)),
    costPerImage: delivered ? cost / delivered : null,
    checkFailures: checkFailures(finishedSnaps),
    rerankHits: rerankHits(finishedSnaps),
    recent: [...stats].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, RECENT),
  };
}
