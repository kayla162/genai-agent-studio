import type {
  BBox, CheckId, CheckStatus, ComfyParam, Fix, LayoutElementId, RagChunk, Render, TemplateId,
} from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { specKey, type JobView } from '@/lib/jobs/view';
import { diffSpecs, type SpecDiff } from './diff';

/* ---------- JSON Prompt 與注入參數 ---------- */

export interface SpecOption { key: string; round: number; templateId: TemplateId }

/** 任務產生過的 Prompt：依輪次、再依模板的標準順序 */
export function specOptions(view: JobView): SpecOption[] {
  return Object.values(view.specs)
    .map((s) => ({ key: specKey(s.round, s.templateId), round: s.round, templateId: s.templateId }))
    .sort((a, b) => a.round - b.round || TEMPLATE_IDS.indexOf(a.templateId) - TEMPLATE_IDS.indexOf(b.templateId));
}

export interface InjectionRow extends ComfyParam {
  /** 同模板上一輪的值；第一輪為 null */
  previous: string | number | null;
  changed: boolean;
}

/** workflow_api.json 注入參數對照：與同模板上一輪相比，標出改變的值 */
export function injectionRows(view: JobView, key: string): InjectionRow[] {
  const spec = view.specs[key];
  if (!spec) return [];
  const prev = view.specs[specKey(spec.round - 1, spec.templateId)];
  return spec.injection.params.map((p) => {
    const before = prev?.injection.params.find((q) => q.nodeId === p.nodeId && q.input === p.input);
    return { ...p, previous: before ? before.value : null, changed: before !== undefined && before.value !== p.value };
  });
}

/* ---------- RAG 召回與 Rerank ---------- */

export interface RerankRow extends Pick<RagChunk, 'source' | 'section' | 'tag' | 'text'> {
  chunkId: string;
  vectorScore: number;
  vectorRank: number;
  rerankScore: number | null;
  rerankRank: number | null;
  /** 引用這段規範、且未通過（失敗或警告）的檢查項 */
  citedBy: CheckId[];
}

/** 第一次檢索的結果：Rerank 後依 Rerank 順序，否則依向量分數 */
export function rerankRows(view: JobView): RerankRow[] {
  const byVector = [...view.ragHits].sort((a, b) => b.vectorScore - a.vectorScore).map((h) => h.chunkId);
  const reranked = view.ragHits.some((h) => h.rerankScore !== undefined);
  const order = reranked ? view.ragHits : [...view.ragHits].sort((a, b) => b.vectorScore - a.vectorScore);
  const cited = new Map<string, Set<CheckId>>();
  for (const id of view.renderIds) {
    for (const c of view.renders[id].checks) {
      if (c.status === 'pass' || !c.ragRef) continue;
      cited.set(c.ragRef, (cited.get(c.ragRef) ?? new Set()).add(c.id));
    }
  }
  return order.map((h, i) => ({
    chunkId: h.chunkId, source: h.source, section: h.section, tag: h.tag, text: h.text,
    vectorScore: h.vectorScore,
    vectorRank: byVector.indexOf(h.chunkId) + 1,
    rerankScore: h.rerankScore ?? null,
    rerankRank: reranked ? i + 1 : null,
    citedBy: [...(cited.get(h.chunkId) ?? [])],
  }));
}

/* ---------- 合規報告與 BBox 疊圖 ---------- */

const SEVERITY: Record<CheckStatus, number> = { pass: 0, warn: 1, fail: 2 };
const worse = (a: CheckStatus | null, b: CheckStatus): CheckStatus => (a === null || SEVERITY[b] > SEVERITY[a] ? b : a);

export interface OverlayBox {
  id: LayoutElementId;
  bbox: BBox;
  /** 指向這個元素的檢查中最嚴重的結果；沒有檢查指向它時為 null */
  status: CheckStatus | null;
  /** 未通過的檢查名稱 */
  issues: string[];
}

export interface Overlay {
  boxes: OverlayBox[];
  /** 針對整張圖的檢查（例如主色色差） */
  canvas: { status: CheckStatus | null; issues: string[] };
}

export function overlayFor(render: Render): Overlay {
  const canvas: Overlay['canvas'] = { status: null, issues: [] };
  const boxes = render.spec.layout.map((b): OverlayBox => ({ id: b.id, bbox: b.bbox, status: null, issues: [] }));
  for (const c of render.checks) {
    const target = c.target === 'canvas' ? canvas : boxes.find((b) => b.id === c.target);
    if (!target) continue;
    target.status = worse(target.status, c.status);
    if (c.status !== 'pass') target.issues.push(c.name);
  }
  return { boxes, canvas };
}

/* ---------- 重試 diff ---------- */

export interface RetryDiff {
  round: number;
  templateId: TemplateId;
  reasons: CheckId[];
  fixes: Fix[];
  requery: boolean;
  /** 改寫前後 Prompt 的差異；下一輪的 Prompt 還沒產生時為空陣列 */
  diffs: SpecDiff[];
  /** 該模板在這一輪、下一輪的最高分；尚未審查時為 null */
  scoreBefore: number | null;
  scoreAfter: number | null;
}

function bestScore(view: JobView, round: number, templateId: TemplateId): number | null {
  const scores = view.renderIds
    .map((id) => view.renders[id])
    .filter((r) => r.round === round && r.templateId === templateId && r.score !== null)
    .map((r) => r.score as number);
  return scores.length ? Math.max(...scores) : null;
}

/** 每次 Query Rewriting：未通過的原因、修正策略，以及改寫前後的 Prompt 差異 */
export function retryDiffs(view: JobView): RetryDiff[] {
  return view.rewrites.map((r) => {
    const before = view.specs[specKey(r.round, r.templateId)];
    const after = view.specs[specKey(r.round + 1, r.templateId)];
    return {
      ...r,
      diffs: before && after ? diffSpecs(before, after) : [],
      scoreBefore: bestScore(view, r.round, r.templateId),
      scoreAfter: bestScore(view, r.round + 1, r.templateId),
    };
  });
}
