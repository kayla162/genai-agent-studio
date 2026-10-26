import type {
  Brand, ChannelTemplate, CheckId, DemoOptions, JobEvent, JobInput, LogLevel, LogSource, Product, RagHit, RagTag,
  Render, RenderNode, TemplateId,
} from '@/types/contract';
import { buildPromptSpec, seedOf } from '@/lib/agent/prompt';
import { planFixes } from '@/lib/agent/fixes';
import { chooseVisualStyle } from '@/lib/agent/style';
import { deepFreeze } from '@/lib/core/freeze';
import { hashString, mulberry32 } from '@/lib/core/num';
import { truncate } from '@/lib/core/text';
import { applyFlaws, FLAWS } from './flaws';
import { reviewRender } from './review';

export interface TimedEvent { at: number; event: JobEvent }

export interface ScenarioContext {
  jobId: string;
  input: JobInput;
  brand: Brand;
  product: Product;
  templates: ChannelTemplate[];
  demo: DemoOptions;
  seed: number;
}

/** 1× 速度下各階段的時間（毫秒）。含一次重試總長 14,500 ms。 */
export const PHASE_MS = {
  parse: 800, retrieveStart: 1100, retrieved: 1600, reranked: 2300,
  prompt: 800, compose: 300, review: 1200, rewrite: 800, save: 400,
} as const;

type SceneNode = Extract<RenderNode, 'generate' | 'upscale'>;

/**
 * ComfyUI 各節點的步數與時間；每輪共 10 個 render.progress、3,200 ms。
 * 與真實 workflow（product_scene_v1.json）相同：SDXL-Lightning 8 步 inpainting，之後以 Lanczos 放大。
 * 去背在商品上傳時就完成，不在這裡；合約的 cutout、relight 不會出現。
 */
export const RENDER_STEPS: Record<SceneNode, { steps: number; ms: number }> = {
  generate: { steps: 8, ms: 2900 },
  upscale: { steps: 2, ms: 300 },
};

const NODE_LABEL: Record<SceneNode, string> = {
  generate: '背景生成（SDXL-Lightning 8 步，商品周圍 inpainting）',
  upscale: '放大（Lanczos，裁切成模板尺寸）',
};

/** 向量召回順序與 Rerank 後順序刻意不同，用來展示 BGE Reranker 的效果 */
const VECTOR_ORDER: RagTag[] = ['layout', 'color', 'history', 'logo', 'law'];
const VECTOR_SCORES = [0.86, 0.84, 0.83, 0.81, 0.79];
const RERANK_ORDER: RagTag[] = ['color', 'law', 'logo', 'layout', 'history'];
const RERANK_SCORES = [0.97, 0.93, 0.88, 0.74, 0.61];

function retrieve(brand: Brand): RagHit[] {
  return VECTOR_ORDER.map((tag, i) => {
    const c = brand.guidelineChunks.find((x) => x.tag === tag && !x.id.endsWith('-alt'));
    if (!c) throw new Error(`Brand ${brand.id} has no ${tag} chunk`);
    return { chunkId: c.id, source: c.source, section: c.section, tag: c.tag, text: c.text, vectorScore: VECTOR_SCORES[i] };
  });
}

function rerank(hits: RagHit[]): RagHit[] {
  return hits
    .map((h) => ({ ...h, rerankScore: RERANK_SCORES[RERANK_ORDER.indexOf(h.tag)] }))
    .sort((a, b) => (b.rerankScore ?? 0) - (a.rerankScore ?? 0));
}

function requeryHit(brand: Brand): RagHit {
  const c = brand.guidelineChunks.find((x) => x.id === `${brand.id}#law-alt`);
  if (!c) throw new Error(`Brand ${brand.id} has no law-alt chunk`);
  return { chunkId: c.id, source: c.source, section: c.section, tag: c.tag, text: c.text, vectorScore: 0.884, rerankScore: 0.95 };
}

export function buildTimeline(ctx: ScenarioContext): TimedEvent[] {
  const { jobId, input, brand, product, templates, demo } = ctx;
  const rng = mulberry32(ctx.seed);
  const out: TimedEvent[] = [];
  const emit = (at: number, event: JobEvent) => out.push({ at: Math.round(at), event });
  const log = (at: number, source: LogSource, message: string, level: LogLevel = 'info') =>
    emit(at, { type: 'log', source, level, message });

  // 1. 接收任務、拆解需求
  emit(0, { type: 'job.accepted', jobId });
  emit(0, { type: 'job.status', stage: 'parsing', round: 0 });
  log(0, 'ws', `→ job.create brand=${brand.id} product=${product.id} templates=${templates.map((t) => t.id).join(',')}`);
  log(300, 'agent', `${input.llm}：拆解需求「${truncate(input.brief, 24)}」`);
  emit(PHASE_MS.parse, { type: 'brief.parsed', parsedBrief: structuredClone(input.parsedBrief) });
  const pb = input.parsedBrief;
  log(PHASE_MS.parse, 'agent', `✓ 語氣=${pb.tone}・檔期=${pb.campaign ?? '無'}・優惠=${pb.offer ?? '無'}`, 'ok');
  const chosen = chooseVisualStyle(brand, pb.tone, input.visualStyleId);
  log(PHASE_MS.parse, 'agent', chosen.note);

  // 2. RAG：Chroma 召回 → BGE Rerank
  emit(PHASE_MS.retrieveStart, { type: 'job.status', stage: 'retrieving', round: 0 });
  log(PHASE_MS.retrieveStart, 'rag', `embed query（bge-m3）→ similarity_search(collection="${brand.id}_ci", top_k=5)`);
  const hits = retrieve(brand);
  emit(PHASE_MS.retrieved, { type: 'rag.retrieved', query: `${brand.name}｜${product.name}｜${input.brief}`, hits });
  log(PHASE_MS.retrieved, 'rag', `召回 ${hits.length} 筆品牌規範`);
  const ranked = rerank(hits);
  emit(PHASE_MS.reranked, { type: 'rag.reranked', hits: ranked });
  log(PHASE_MS.reranked, 'rag', `✓ BGE Reranker 重新排序：${ranked.map((h) => h.tag).join(' > ')}`, 'ok');
  const ragRefs = ranked.map((h) => h.chunkId);

  let t: number = PHASE_MS.reranked;
  let round = 1;
  let pending = [...templates];
  let fixesForNext: CheckId[] = [];
  const best: Partial<Record<TemplateId, string>> = {};
  let success = false;

  for (;;) {
    const flawed = demo.forceAllFail || (demo.firstRoundFail && round === 1);

    // 3. Prompt 構建（JSON Prompt + BBox）
    emit(t, { type: 'job.status', stage: 'prompting', round });
    const specs = pending.map((template) => {
      const spec = buildPromptSpec({
        jobId, round, brand, product, brief: input.parsedBrief, template, engine: input.engine,
        seed: 100_000_000 + Math.floor(rng() * 900_000_000), ragRefs, fixes: fixesForNext, visualStyleId: chosen.style.id,
      });
      return flawed ? applyFlaws(spec, FLAWS, brand) : spec;
    });
    specs.forEach((spec, i) =>
      emit(t + ((i + 1) * PHASE_MS.prompt) / specs.length, { type: 'prompt.generated', round, templateId: spec.templateId, spec }),
    );
    log(t + PHASE_MS.prompt, 'agent', `✓ 第 ${round} 輪 JSON Prompt：${specs.length} 個模板 × ${specs[0].layout.length} 個 BBox`, 'ok');
    t += PHASE_MS.prompt;

    // 4. ComfyUI：背景生成（商品周圍 inpainting）→ 放大
    emit(t, { type: 'job.status', stage: 'rendering', round });
    for (const spec of specs) {
      emit(t, { type: 'comfy.queued', round, templateId: spec.templateId, promptId: `${jobId}_r${round}_${spec.templateId}`, injection: spec.injection });
    }
    log(t, 'comfy', `ws → ComfyUI /prompt × ${specs.length}（${specs[0].injection.workflowFile}，batch=${input.variantsPerTemplate}）`);
    for (const node of ['generate', 'upscale'] as const) {
      const { steps, ms } = RENDER_STEPS[node];
      for (let s = 1; s <= steps; s++) emit(t + (s * ms) / steps, { type: 'render.progress', round, node, step: s, maxStep: steps });
      t += ms;
      log(t, 'comfy', `✓ ${NODE_LABEL[node]} 完成`);
    }
    const renders: Render[] = specs.flatMap((spec) =>
      Array.from({ length: input.variantsPerTemplate }, (_, v): Render => ({
        id: `${jobId}_r${round}_${spec.templateId}_v${v}`, jobId, round, templateId: spec.templateId, variant: v,
        background: { kind: 'procedural', seed: seedOf(spec) + v, palette: spec.palette, style: brand.id },
        spec, score: null, passed: null, checks: [],
      })),
    );
    emit(t, { type: 'render.completed', round, renders });

    // 5. 文字排版合成
    emit(t, { type: 'job.status', stage: 'composing', round });
    log(t, 'compose', `排版引擎疊加文字圖層（${renders.length} 張）`);
    t += PHASE_MS.compose;

    // 6. 合規審查（規則 + VLM）
    emit(t, { type: 'job.status', stage: 'reviewing', round });
    log(t, 'vlm', `${input.vlm}：審查 ${renders.length} 張 × 11 項`);
    const results = renders.map((render) => ({
      render, result: reviewRender(render.spec, brand, render.variant, hashString(render.id) ^ ctx.seed),
    }));
    const dt = PHASE_MS.review / results.reduce((n, x) => n + x.result.checks.length, 0);
    let k = 0;
    for (const { render, result } of results) {
      for (const check of result.checks) emit(t + ++k * dt, { type: 'review.check', round, renderId: render.id, check });
      emit(t + k * dt, {
        type: 'review.completed', round, renderId: render.id, score: result.score, passed: result.passed, image: null,
      });
    }
    t += PHASE_MS.review;

    const byScore = (id: TemplateId) =>
      results.filter((x) => x.render.templateId === id).sort((a, b) => b.result.score - a.result.score);
    const failed: ChannelTemplate[] = [];
    for (const template of pending) {
      const top = byScore(template.id).find((x) => x.result.passed);
      if (top) best[template.id] = top.render.id;
      else failed.push(template);
    }
    log(t, 'vlm', `第 ${round} 輪：${pending.length - failed.length}/${pending.length} 個模板通過`, failed.length ? 'warn' : 'ok');

    if (!failed.length) { success = true; break; }
    if (round > input.maxRetries) break;

    // 7. Query Rewriting（必要時重新檢索合規用語）
    emit(t, { type: 'job.status', stage: 'rewriting', round });
    const reasons = new Set<CheckId>();
    const altId = `${brand.id}#law-alt`;
    const altAlreadyRetrieved = ragRefs.includes(altId);
    let requery = false;
    for (const template of failed) {
      const top = byScore(template.id)[0];
      const failing = top.result.checks.filter((c) => c.status !== 'pass').map((c) => c.id);
      failing.forEach((id) => reasons.add(id));
      const needRequery = failing.includes('banned_words') || failing.includes('vlm_exaggeration');
      requery ||= needRequery;
      emit(t, {
        type: 'rewrite.started', round, templateId: template.id, reasons: failing,
        fixes: planFixes(top.result.checks, brand, top.render.spec), requery: needRequery && !altAlreadyRetrieved,
      });
    }
    log(t, 'api', `觸發 Query Rewriting（重試 ${round}/${input.maxRetries}）`, 'warn');
    if (requery && !altAlreadyRetrieved) {
      const hit = requeryHit(brand);
      emit(t + PHASE_MS.rewrite / 2, { type: 'rag.retrieved', query: `${brand.category} 禁用詞 合規替代用語`, hits: [hit] });
      log(t + PHASE_MS.rewrite / 2, 'rag', `re-query → ${hit.chunkId}（${hit.vectorScore}）`, 'ok');
      ragRefs.push(altId);
    }
    fixesForNext = [...new Set([...fixesForNext, ...reasons])];
    t += PHASE_MS.rewrite;
    pending = failed;
    round++;
  }

  // 8. 寫入 DB 並回傳
  emit(t, { type: 'job.status', stage: 'saving', round });
  log(t, 'db', `INSERT INTO renders（${Object.keys(best).length} 張最佳候選）`);
  t += PHASE_MS.save;
  if (success) {
    emit(t, { type: 'job.completed', jobId, bestRenderIds: best });
    emit(t, { type: 'job.status', stage: 'done', round });
    log(t, 'ws', '← job.completed', 'ok');
  } else {
    emit(t, { type: 'job.needs_review', jobId, reason: '已達最大重試次數，仍未通過合規審查' });
    emit(t, { type: 'job.status', stage: 'needs_review', round });
    log(t, 'ws', '← job.needs_review', 'warn');
  }
  // Array.prototype.sort 是穩定排序：同一時間點的事件維持加入順序
  return deepFreeze(out.sort((a, b) => a.at - b.at));
}
