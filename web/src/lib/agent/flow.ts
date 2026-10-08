import type { JobMessage, JobStage } from '@/types/contract';

export type FlowNodeId = 'orchestrator' | 'brief' | 'rag' | 'prompt' | 'comfy' | 'compose' | 'review' | 'save';
/** warn：曾經未通過、重試後完成；error：需人工審核，或在此節點取消／失敗 */
export type FlowStatus = 'idle' | 'active' | 'done' | 'warn' | 'error';

export interface FlowNodeDef { id: FlowNodeId; step: number; label: string; tech: string }

/** 規格第 5 節的流程節點 */
export const FLOW_NODES: FlowNodeDef[] = [
  { id: 'orchestrator', step: 1, label: 'Orchestrator', tech: 'FastAPI' },
  { id: 'brief', step: 2, label: '需求拆解 Agent', tech: 'LLM' },
  { id: 'rag', step: 3, label: 'RAG 檢索', tech: 'Chroma 召回 → BGE Rerank' },
  { id: 'prompt', step: 4, label: 'Prompt 構建', tech: 'JSON Prompt + BBox' },
  { id: 'comfy', step: 5, label: 'ComfyUI', tech: '去背 → 背景 → 打光 → 放大' },
  { id: 'compose', step: 6, label: '文字排版合成', tech: '排版引擎' },
  { id: 'review', step: 7, label: '合規審查', tech: '規則 + VLM' },
  { id: 'save', step: 8, label: '寫入 DB 與回傳', tech: 'DB + WebSocket' },
];

const STAGE_NODE: Partial<Record<JobStage, FlowNodeId>> = {
  parsing: 'brief', retrieving: 'rag', prompting: 'prompt', rendering: 'comfy', composing: 'compose',
  reviewing: 'review', saving: 'save',
};

export interface FlowNodeState {
  status: FlowStatus;
  /** 進入幾次（Prompt 構建等節點每輪一次） */
  visits: number;
  /** 停留的總時間（依事件時間戳） */
  ms: number;
}

export interface FlowLoop {
  /** Query Rewriting 次數 */
  count: number;
  /** 改寫時是否重新檢索合規用語 */
  requery: boolean;
  active: boolean;
  ms: number;
}

export interface FlowState {
  nodes: Record<FlowNodeId, FlowNodeState>;
  /** 審查未通過 → Query Rewriting → 回到 Prompt 構建（必要時重新檢索） */
  loop: FlowLoop;
  /** 第一則到最後一則訊息的時間 */
  elapsedMs: number;
}

/** 由事件訊息推算每個流程節點的狀態與耗時 */
export function flowState(messages: JobMessage[]): FlowState {
  const nodes = Object.fromEntries(
    FLOW_NODES.map((n): [FlowNodeId, FlowNodeState] => [n.id, { status: 'idle', visits: 0, ms: 0 }]),
  ) as Record<FlowNodeId, FlowNodeState>;
  const loop: FlowLoop = { count: 0, requery: false, active: false, ms: 0 };
  let open: { node: FlowNodeId | 'loop'; since: number } | null = null;
  let last: FlowNodeId | 'loop' | null = null;
  let stage: JobStage | null = null;

  const close = (until: number) => {
    if (!open) return;
    if (open.node === 'loop') loop.ms += until - open.since;
    else nodes[open.node].ms += until - open.since;
    open = null;
  };

  for (const m of messages) {
    if (m.type === 'job.accepted') nodes.orchestrator.visits = 1;
    if (m.type === 'rewrite.started' && m.requery) loop.requery = true;
    if (m.type !== 'job.status') continue;
    const at = Date.parse(m.ts);
    close(at);
    stage = m.stage;
    const node = m.stage === 'rewriting' ? 'loop' : STAGE_NODE[m.stage];
    if (!node) continue;
    if (node === 'loop') loop.count++;
    else nodes[node].visits++;
    open = { node, since: at };
    last = node;
  }

  const first = messages[0];
  const end = messages.at(-1);
  if (end) close(Date.parse(end.ts));

  const stopped = stage === 'cancelled' || stage === 'failed';
  const running = stage !== null && stage !== 'done' && stage !== 'needs_review' && !stopped;
  for (const n of FLOW_NODES) if (nodes[n.id].visits > 0) nodes[n.id].status = 'done';
  if (loop.count > 0) nodes.review.status = 'warn';
  if (stage === 'needs_review') nodes.review.status = 'error';
  if (running && last && last !== 'loop') nodes[last].status = 'active';
  if (stopped && last && last !== 'loop') nodes[last].status = 'error';
  loop.active = stage === 'rewriting';
  if (nodes.orchestrator.visits) nodes.orchestrator.status = running ? 'active' : stopped ? 'error' : 'done';

  const elapsedMs = first && end ? Date.parse(end.ts) - Date.parse(first.ts) : 0;
  nodes.orchestrator.ms = elapsedMs;
  return { nodes, loop, elapsedMs };
}
