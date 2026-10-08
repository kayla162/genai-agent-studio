import type {
  CheckId, Fix, JobEvent, JobStage, JobSummary, LogLevel, LogSource, ParsedBrief, PromptSpec, RagHit, Render, RenderNode,
  TemplateId,
} from '@/types/contract';

export type JobOutcome = 'running' | 'done' | 'needs_review' | 'cancelled';
export interface RewriteInfo { round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
export interface LogLine { source: LogSource; level: LogLevel; message: string }
export interface RenderProgress { round: number; node: RenderNode; step: number; maxStep: number }

/** 由事件串流累積出來的任務畫面狀態。mock 與 live 共用（UI 只看事件，不看實作）。 */
export interface JobView {
  jobId: string | null;
  stage: JobStage | null;
  round: number;
  outcome: JobOutcome;
  parsedBrief: ParsedBrief | null;
  /** 第一次檢索的結果（Rerank 後會帶 rerankScore） */
  ragHits: RagHit[];
  /** Query Rewriting 時重新檢索到的切塊 */
  requeryHits: RagHit[];
  /** key 為 specKey(round, templateId) */
  specs: Record<string, PromptSpec>;
  renders: Record<string, Render>;
  /** 依收到的順序 */
  renderIds: string[];
  progress: RenderProgress | null;
  rewrites: RewriteInfo[];
  bestRenderIds: Partial<Record<TemplateId, string>>;
  needsReviewReason: string | null;
  logs: LogLine[];
}

export const specKey = (round: number, templateId: TemplateId) => `${round}:${templateId}`;

export const STAGE_LABEL: Record<JobStage, string> = {
  parsing: '需求拆解',
  retrieving: 'RAG 檢索',
  prompting: 'Prompt 構建',
  rendering: 'ComfyUI 生成',
  composing: '文字排版',
  reviewing: '合規審查',
  rewriting: 'Query Rewriting',
  saving: '寫入資料庫',
  done: '完成',
  needs_review: '需人工審核',
  cancelled: '已取消',
};

export function emptyJobView(jobId: string | null = null): JobView {
  return {
    jobId, stage: null, round: 0, outcome: 'running', parsedBrief: null, ragHits: [], requeryHits: [], specs: {},
    renders: {}, renderIds: [], progress: null, rewrites: [], bestRenderIds: {}, needsReviewReason: null, logs: [],
  };
}

const OUTCOME: Partial<Record<JobStage, JobOutcome>> = { done: 'done', needs_review: 'needs_review', cancelled: 'cancelled' };

/** 純函式：回傳新的 view，不修改輸入（事件是凍結的物件） */
export function reduceJob(v: JobView, e: JobEvent): JobView {
  switch (e.type) {
    case 'job.accepted':
      return { ...v, jobId: e.jobId };
    case 'job.status':
      return { ...v, stage: e.stage, round: e.round, outcome: OUTCOME[e.stage] ?? v.outcome };
    case 'brief.parsed':
      return { ...v, parsedBrief: e.parsedBrief };
    case 'rag.retrieved':
      return v.stage === 'rewriting' ? { ...v, requeryHits: [...v.requeryHits, ...e.hits] } : { ...v, ragHits: e.hits };
    case 'rag.reranked':
      return { ...v, ragHits: e.hits };
    case 'prompt.generated':
      return { ...v, specs: { ...v.specs, [specKey(e.round, e.templateId)]: e.spec } };
    case 'comfy.queued':
      return v;
    case 'render.progress':
      return { ...v, progress: { round: e.round, node: e.node, step: e.step, maxStep: e.maxStep } };
    case 'render.completed': {
      const renders = { ...v.renders };
      for (const r of e.renders) renders[r.id] = r;
      return { ...v, renders, renderIds: [...v.renderIds, ...e.renders.map((r) => r.id).filter((id) => !v.renders[id])] };
    }
    case 'review.check': {
      const r = v.renders[e.renderId];
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, checks: [...r.checks, e.check] } } } : v;
    }
    case 'review.completed': {
      const r = v.renders[e.renderId];
      return r ? { ...v, renders: { ...v.renders, [r.id]: { ...r, score: e.score, passed: e.passed } } } : v;
    }
    case 'rewrite.started':
      return {
        ...v,
        rewrites: [...v.rewrites, { round: e.round, templateId: e.templateId, reasons: e.reasons, fixes: e.fixes, requery: e.requery }],
      };
    case 'job.completed':
      return { ...v, bestRenderIds: e.bestRenderIds };
    case 'job.needs_review':
      return { ...v, needsReviewReason: e.reason };
    case 'log':
      return { ...v, logs: [...v.logs, { source: e.source, level: e.level, message: e.message }] };
  }
}

export const applyEvents = (events: JobEvent[], jobId: string | null = null): JobView =>
  events.reduce(reduceJob, emptyJobView(jobId));

/** 每個模板最後一輪的候選（依 variant 排序）；結果牆只顯示這些 */
export function finalCandidates(v: JobView): Partial<Record<TemplateId, Render[]>> {
  const out: Partial<Record<TemplateId, Render[]>> = {};
  for (const id of v.renderIds) {
    const r = v.renders[id];
    const list = out[r.templateId];
    if (!list || list[0].round < r.round) out[r.templateId] = [r];
    else if (list[0].round === r.round) list.push(r);
  }
  for (const list of Object.values(out)) list.sort((a, b) => a.variant - b.variant);
  return out;
}

/** 預設選擇：任務的最佳候選優先；需人工審核時取最後一輪分數最高的 */
export function defaultSelection(v: JobView): Partial<Record<TemplateId, string>> {
  const out: Partial<Record<TemplateId, string>> = {};
  for (const [templateId, list] of Object.entries(finalCandidates(v)) as [TemplateId, Render[]][]) {
    const best = v.bestRenderIds[templateId];
    out[templateId] = best ?? [...list].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))[0].id;
  }
  return out;
}

/** ComfyUI 各節點在一輪生成中所佔的比例（依 1× 時間：400／2000／500／300 ms） */
const NODE_SPAN: Record<RenderNode, [start: number, span: number]> = {
  cutout: [0, 0.125],
  generate: [0.125, 0.625],
  relight: [0.75, 0.156],
  upscale: [0.906, 0.094],
};

/** 精簡進度條用的 0–1 進度。重試時每一輪會從 Prompt 構建重新往前推。 */
export function jobProgress(v: JobView): number {
  if (v.outcome === 'done' || v.outcome === 'needs_review') return 1;
  switch (v.stage) {
    case null: return 0;
    case 'parsing': return 0.04;
    case 'retrieving': return 0.1;
    case 'prompting': return 0.16;
    case 'rendering': {
      const p = v.progress && v.progress.round === v.round ? v.progress : null;
      const frac = p ? NODE_SPAN[p.node][0] + (NODE_SPAN[p.node][1] * p.step) / p.maxStep : 0;
      return 0.2 + 0.5 * frac;
    }
    case 'composing': return 0.72;
    case 'reviewing': {
      const current = v.renderIds.map((id) => v.renders[id]).filter((r) => r.round === v.round);
      const reviewed = current.filter((r) => r.score !== null).length;
      return 0.74 + (0.18 * reviewed) / Math.max(1, current.length);
    }
    case 'rewriting': return 0.93;
    case 'saving': return 0.97;
    default: return 1;
  }
}

/** 任務列表是讀取當下的快照；正在檢視的任務改用事件串流的即時階段，其他任務不變 */
export function withLiveStage(jobs: JobSummary[], v: JobView): JobSummary[] {
  const { jobId, stage, round, outcome } = v;
  if (!stage) return jobs;
  return jobs.map((j) => (j.id === jobId ? { ...j, stage, round, finished: outcome !== 'running' } : j));
}
