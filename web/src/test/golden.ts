import type { DemoOptions, JobEvent, JobInput, JobMessage, JobStage, TemplateId } from '@/types/contract';
import type { GuardIssue, SpecDraft, VlmVerdict } from '@/types/agent';
import { PRODUCT_SCENE } from '@/lib/agent/comfy';
import { finalizeSpec, type GuardRequest } from '@/lib/agent/guard';
import type { JobSnapshot } from '@/lib/api/client';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { sampleJobs } from '@/lib/api/mock/samples';
import { buildTimeline } from '@/lib/api/mock/scenario';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { hashString, mulberry32 } from '@/lib/core/num';
import { chunkDocument, embedPreview } from '@/lib/rag/chunk';
import type { BackgroundPalette } from '@/lib/review/background';
import { dashboardStats } from '@/lib/stats/dashboard';
import { CHUNK_SAMPLES, PREVIEW_SAMPLES } from './chunk-samples';
import { cleanSpec, draftOf } from './fixtures';

/**
 * 給後端（Python）一致性測試的固定測資，寫在 repo 根目錄的 contracts/fixtures/。
 * 第一階段的 TypeScript 是行為的來源：後端解析這些資料、用同樣的輸入重算，結果必須相同。
 * 修改相關程式後執行 `npm run fixtures` 重新產生；golden.test.ts 會檢查檔案是否過期。
 */
export const FIXTURES_DIR = new URL('../../../contracts/fixtures/', import.meta.url);

const DEFAULT_DEMO: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };

interface Scenario {
  name: string;
  jobId: string;
  brandId: string;
  brief: string;
  templateIds: TemplateId[];
  variants: number;
  maxRetries: number;
  demo: Partial<DemoOptions>;
}

/** 模擬模式的劇本：預設首輪失敗後重試通過、全部失敗轉人工審核、首輪就通過 */
const SCENARIOS: Scenario[] = [
  {
    name: 'selune-retry', jobId: 'job_20261007_1000_a1b2', brandId: 'selune',
    brief: '幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺', templateIds: ['ig-post', 'story'], variants: 2,
    maxRetries: 2, demo: {},
  },
  {
    name: 'selune-needs-review', jobId: 'job_20261007_1010_c3d4', brandId: 'selune',
    brief: '雙11 11/1–11/11 精華液限時85折，要專業科研感', templateIds: ['ecom-main'], variants: 2, maxRetries: 1,
    demo: { forceAllFail: true },
  },
  {
    name: 'misty-first-pass', jobId: 'job_20261007_1020_e5f6', brandId: 'misty-isle',
    brief: '幫我設計一款簡約風格的冷萃咖啡宣傳海報', templateIds: ['banner'], variants: 3, maxRetries: 2,
    demo: { firstRoundFail: false },
  },
];

function scenarioInput(s: Scenario): JobInput {
  const brand = getBrandById(s.brandId);
  const product = SAMPLE_PRODUCTS.find((p) => p.brandId === brand.id)!;
  return {
    brandId: brand.id, productId: product.id, brief: s.brief, parsedBrief: parseBrief(s.brief, brand, product),
    templateIds: s.templateIds, variantsPerTemplate: s.variants, llm: 'Gemini 3.7 Flash', engine: 'comfyui',
    vlm: 'Gemini 3.7 Vision', maxRetries: s.maxRetries, visualStyleId: null,
  };
}

function timeline(jobId: string, input: JobInput, demo: DemoOptions): { at: number; event: JobEvent }[] {
  const brand = getBrandById(input.brandId);
  const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId)!;
  const templates = input.templateIds.map((id) => getTemplate(id));
  return buildTimeline({ jobId, input, brand, product, templates, demo, seed: hashString(jobId) }).map(({ at, event }) => ({ at, event }));
}

function snapshot(jobId: string, input: JobInput, createdAt: Date, events: JobEvent[], ats: number[]): JobSnapshot {
  const messages: JobMessage[] = events.map((e, i) => ({ ...e, seq: i + 1, ts: new Date(createdAt.getTime() + ats[i]).toISOString() }));
  let stage: JobStage = 'parsing';
  let round = 0;
  let bestRenderIds: JobSnapshot['summary']['bestRenderIds'] = {};
  for (const e of events) {
    if (e.type === 'job.status') ({ stage, round } = e);
    if (e.type === 'job.completed') bestRenderIds = e.bestRenderIds;
  }
  const finished = ['done', 'needs_review', 'cancelled', 'failed'].includes(stage);
  return { summary: { id: jobId, input, createdAt: createdAt.toISOString(), stage, round, finished, bestRenderIds }, events: messages };
}

/** 儀表板統計的輸入：6 筆示範任務（含需人工審核、首輪通過、Ideogram），加上 1 筆取消、1 筆失敗（兩者都不列入統計） */
function statsSnapshots(): JobSnapshot[] {
  const now = new Date('2026-10-07T02:00:00.000Z');
  const seeded = sampleJobs(6, now).map(({ input, demo, createdAt }, i) => {
    const jobId = `job_sample_${String(i + 1).padStart(2, '0')}`;
    const tl = timeline(jobId, input, demo);
    return snapshot(jobId, input, createdAt, tl.map((x) => x.event), tl.map((x) => x.at));
  });
  const input = scenarioInput(SCENARIOS[0]);
  const tl = timeline('job_sample_cancelled', input, DEFAULT_DEMO);
  const cut = tl.findIndex((x) => x.event.type === 'job.status' && x.event.stage === 'rendering');
  const head = tl.slice(0, cut + 1);
  const at = head.at(-1)!.at;
  const cancelled = snapshot(
    'job_sample_cancelled', input, new Date('2026-10-07T01:00:00.000Z'),
    [...head.map((x) => x.event), { type: 'job.status', stage: 'cancelled', round: 1 }], [...head.map((x) => x.at), at],
  );
  const failed = snapshot(
    'job_sample_failed', input, new Date('2026-10-07T01:30:00.000Z'),
    [
      ...head.map((x) => x.event),
      { type: 'job.failed', jobId: 'job_sample_failed', reason: 'ComfyUI 沒有回應' },
      { type: 'job.status', stage: 'failed', round: 1 },
    ],
    [...head.map((x) => x.at), at, at],
  );
  return [...seeded, cancelled, failed];
}

/** 統計用不到 PromptSpec 與注入參數：拿掉以縮小檔案（後端的統計直接處理事件 JSON） */
function slim(snap: JobSnapshot): unknown {
  return {
    summary: snap.summary,
    events: snap.events.map((m) => {
      if (m.type === 'prompt.generated') return { ...m, spec: null };
      if (m.type === 'comfy.queued') return { ...m, injection: null };
      if (m.type === 'render.completed') return { ...m, renders: m.renders.map((r) => ({ ...r, spec: null })) };
      return m;
    }),
  };
}

/**
 * Gemini 的結構化輸出與護欄結果的範例（後端 gemini_types.py 解析，確認兩邊的欄位一致）：
 * 合格的 SpecDraft、涵蓋每一種問題代碼的 GuardIssue、三種狀態都有的 VlmVerdict；
 * 以及 composer 量到的背景色系（BackgroundPalette，後端 ports.py 解析），有色系外顏色與沒有的各一個。
 */
function agentFixtures(): {
  specDraft: SpecDraft; guardIssues: GuardIssue[]; vlmVerdict: VlmVerdict; backgroundPalettes: BackgroundPalette[];
} {
  const spec = cleanSpec();
  const brand = getBrandById('selune');
  const product = { ...SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!, name: '極光精華✨这款' };
  const text = '週年慶 2026/10/15–11/15 溫柔療癒';
  const request: GuardRequest = {
    jobId: 'job_agent', round: 1, brand: { ...brand, bannedWords: [...brand.bannedWords, '奇蹟'] }, product,
    brief: parseBrief(text, brand, product), text, templateId: 'ig-post', engine: 'comfyui', seed: 42, ragRefs: [], fixes: [],
    visualStyleId: 'moonlight',
  };
  const specDraft = draftOf(spec);
  const copyFlaws: SpecDraft = {
    ...specDraft,
    headline: ['这一夜修護', '醒來透亮發光醒來透亮✨'],
    subhead: '奇蹟般的透亮光采',
    features: ['買二送一'],
    badge: { top: '週年慶限定', main: ' ', sub: 'LIMITED OFFER' },
    layout: specDraft.layout.filter((b) => b.id !== 'price'),
    scene: '珍珠托盤上的精華液',
  };
  const layoutFlaws: SpecDraft = {
    ...specDraft,
    layout: specDraft.layout.map((b) => (b.id === 'headline' ? { ...b, bbox: [101, 216, 864, 30] } : b)),
  };
  const ratio = { ...request, brand: { ...request.brand, rules: { ...brand.rules, productRatio: [0.4, 0.6] as [number, number] } } };
  const guardIssues = [...finalizeSpec(copyFlaws, request).issues, ...finalizeSpec(layoutFlaws, ratio).issues];
  const vlmVerdict: VlmVerdict = {
    lines: ['SÉLUNE', '一夜溫柔修護', '醒來透□發光', '7天感受透亮光采・專業修護配方*'],
    exaggeration: { status: 'pass', phrases: [], reason: '' },
    occlusion: { status: 'warn', elements: ['logo', 'headline'], reason: 'Logo 與標題太靠近' },
    quality: { status: 'fail', issues: ['商品邊緣模糊'], reason: '商品主體失焦' },
  };
  const backgroundPalettes: BackgroundPalette[] = [
    { offShare: 0.4213, offHex: '#3FD27A', sampled: 61234 },
    { offShare: 0, offHex: null, sampled: 49152 },
  ];
  return { specDraft, guardIssues, vlmVerdict, backgroundPalettes };
}

export function goldenFixtures(): Record<string, unknown> {
  const out: Record<string, unknown> = {
    'agent.json': agentFixtures(),
    // ComfyUI 的參數對照表：pytest 確認與 comfyui/workflows/product_scene_v1.params.json 相同
    'comfy.json': PRODUCT_SCENE,
    'brands.json': { brands: BRANDS, products: SAMPLE_PRODUCTS, templates: CHANNEL_TEMPLATES },
    'rng.json': {
      hashString: ['', 'a', 'selune#color', '週年慶', 'job_20261007_1000_a1b2'].map((s) => [s, hashString(s)]),
      mulberry32: [0, 1, 42, 123456789, -5, 4294967295].map((seed) => {
        const rng = mulberry32(seed);
        return [seed, Array.from({ length: 5 }, () => rng())];
      }),
    },
    'chunks.json': {
      documents: CHUNK_SAMPLES.map((d) => {
        const chunks = chunkDocument(d.brandId, d, { maxChars: d.maxChars });
        return { ...d, chunks, previews: chunks.map((c) => embedPreview(c.text)) };
      }),
      previews: PREVIEW_SAMPLES.map((s) => ({ ...s, values: embedPreview(s.text, s.n) })),
    },
  };
  for (const s of SCENARIOS) {
    const demo = { ...DEFAULT_DEMO, ...s.demo };
    const input = scenarioInput(s);
    out[`timelines/${s.name}.json`] = { name: s.name, jobId: s.jobId, demo, input, events: timeline(s.jobId, input, demo) };
  }
  const snaps = statsSnapshots();
  out['stats.json'] = {
    snapshots: snaps.map(slim),
    cases: [null, 'selune', 'misty-isle'].map((brandId) => ({
      brandId, stats: dashboardStats(brandId ? snaps.filter((s) => s.summary.input.brandId === brandId) : snaps),
    })),
  };
  return out;
}
