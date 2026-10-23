import {
  LAYOUT_ELEMENT_IDS, TEMPLATE_IDS,
  type Brand, type CheckId, type Engine, type ParsedBrief, type Product, type PromptSpec, type ReviewCheck, type TemplateId,
} from '@/types/contract';
import type { SpecDraft, VlmVerdict } from '@/types/agent';
import { planFixes } from '@/lib/agent/fixes';
import { finalizeSpec, type GuardRequest } from '@/lib/agent/guard';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { reviewRender } from '@/lib/api/mock/review';
import { missingGlyphs } from '@/lib/compose/glyphs';
import { computeLayout } from '@/lib/compose/layout';
import { composePoster } from '@/lib/compose/scene';
import { getTemplate } from '@/lib/compose/templates';
import { expectedSegments, ocrDiffs } from '@/lib/review/ocr';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { contentVlmChecks, geminiVlmChecks } from '@/lib/review/vlm';
import { renderPoster, type RenderPosterInput } from './poster';

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}

/** handler 回傳這個型別時，伺服器直接送出位元組與標頭（其他回傳值一律轉成 JSON） */
export class BinaryResponse {
  constructor(
    readonly body: Buffer,
    readonly contentType: string,
    readonly headers: Record<string, string> = {},
  ) {}
}

/** 可以是同步或非同步（回傳 Promise）的函式 */
type Handler = (body: never) => unknown;

const HEX = /^#[0-9a-f]{6}$/i;
const VLM_STATUSES = ['pass', 'warn', 'fail'];

/* 輸入格式的檢查：後端已經以 Pydantic 驗證過，這裡只擋下格式不對的請求，以中文說明哪個欄位有問題 */
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string');

function ensure(ok: boolean, message: string): asserts ok {
  if (!ok) throw new Error(message);
}

function checkDraft(draft: unknown): asserts draft is SpecDraft {
  ensure(isObject(draft), 'draft 必須是物件');
  ensure(isStrings(draft.headline) && draft.headline.length === 2, 'draft.headline 必須是 2 個字串');
  ensure(isStrings(draft.features), 'draft.features 必須是字串陣列');
  ensure(isObject(draft.badge) && ['top', 'main', 'sub'].every((k) => typeof (draft.badge as Record<string, unknown>)[k] === 'string'),
    'draft.badge 必須有 top、main、sub 三個字串');
  for (const key of ['subhead', 'priceLabel', 'scene', 'negativeExtra', 'rationale']) {
    ensure(typeof draft[key] === 'string', `draft.${key} 必須是字串`);
  }
  ensure(Array.isArray(draft.layout), 'draft.layout 必須是陣列');
  for (const [i, box] of draft.layout.entries()) {
    ensure(isObject(box) && typeof box.id === 'string' && Array.isArray(box.bbox) && box.bbox.every((n) => typeof n === 'number'),
      `draft.layout.${i} 必須是 { id, bbox: [x, y, w, h] }`);
  }
}

function checkRequest(request: unknown): asserts request is GuardRequest {
  ensure(isObject(request), 'request 必須是物件');
  for (const key of ['brand', 'product', 'brief']) ensure(isObject(request[key]), `request.${key} 必須是物件`);
  ensure((TEMPLATE_IDS as readonly unknown[]).includes(request.templateId), `request.templateId 不是可用的模板：${String(request.templateId)}`);
  ensure(typeof request.text === 'string', 'request.text 必須是字串');
  ensure(isStrings(request.ragRefs) && isStrings(request.fixes), 'request.ragRefs 與 request.fixes 必須是字串陣列');
}

function checkVerdict(vlm: unknown): asserts vlm is VlmVerdict {
  ensure(isObject(vlm), 'vlm 必須是物件或 null');
  ensure(isStrings(vlm.lines), 'vlm.lines 必須是字串陣列');
  for (const key of ['exaggeration', 'occlusion', 'quality']) {
    const item = vlm[key];
    ensure(isObject(item) && VLM_STATUSES.includes(item.status as string) && typeof item.reason === 'string',
      `vlm.${key} 必須有 status（pass、warn、fail）與 reason`);
  }
  ensure(isStrings((vlm.exaggeration as Record<string, unknown>).phrases), 'vlm.exaggeration.phrases 必須是字串陣列');
  const elements = (vlm.occlusion as Record<string, unknown>).elements;
  ensure(isStrings(elements) && elements.every((e) => (LAYOUT_ELEMENT_IDS as readonly string[]).includes(e)),
    'vlm.occlusion.elements 必須是版面元素 id 的陣列');
  ensure(isStrings((vlm.quality as Record<string, unknown>).issues), 'vlm.quality.issues 必須是字串陣列');
}

/**
 * live 模式的審查：7 項規則加 3 項 VLM 檢查，分數不加隨機抖動。
 * vlm 有值（AGENT_MODE=gemini）時 VLM 三項用 Gemini 的判讀，並以轉錄比對海報上的文字（ocrDiffs）；
 * vlmScale 為送出給 VLM 的圖片與畫布的比例。vlm 為 null 或省略時與 6A 相同（依內容判斷）。
 */
function reviewPoster({ spec, brand, measuredPrimary, vlm = null, vlmScale = 1 }: {
  spec: PromptSpec; brand: Brand; measuredPrimary: string | null; vlm?: VlmVerdict | null; vlmScale?: number;
}): { checks: ReviewCheck[]; score: number; passed: boolean } {
  if (measuredPrimary !== null && !(typeof measuredPrimary === 'string' && HEX.test(measuredPrimary))) {
    throw new Error(`measuredPrimary 必須是 #RRGGBB 或 null：${JSON.stringify(measuredPrimary)}`);
  }
  if (vlm === null) {
    const checks = [...runRuleChecks({ brand, spec, measuredPrimary }), ...contentVlmChecks(spec, brand)];
    return { checks, ...scoreChecks(checks, 0) };
  }
  checkVerdict(vlm);
  ensure(typeof vlmScale === 'number' && vlmScale > 0, 'vlmScale 必須是大於 0 的數字');
  const segments = expectedSegments(composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: spec.copy, brand }));
  const ocr = ocrDiffs(vlm.lines, segments, vlmScale);
  const checks = [...runRuleChecks({ brand, spec, measuredPrimary, ocr }), ...geminiVlmChecks(vlm, spec, brand)];
  return { checks, ...scoreChecks(checks, 0) };
}

/**
 * 後端呼叫的 TypeScript 邏輯：版型、live 模式的繪製與審查，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

  /** 審查用海報：PNG，標頭帶量到的主色（量不到時為空字串）與它的佔比（0–1） */
  '/render': async (input: RenderPosterInput) => {
    const { png, measured } = await renderPoster(input);
    return new BinaryResponse(png, 'image/png', {
      'X-Measured-Primary': measured.hex ?? '',
      'X-Primary-Share': String(Number(measured.share.toFixed(4))),
    });
  },

  '/review': reviewPoster,

  /** Prompt 構建的程式護欄（AGENT_MODE=gemini）：{ spec, issues } */
  '/spec': ({ draft, request }: { draft: unknown; request: unknown }) => {
    checkDraft(draft);
    checkRequest(request);
    return finalizeSpec(draft, request);
  },

  /** Query Rewriting 的修正項：與 /sim/fixes 相同的 planFixes（Gemini 漏掉的檢查以此補上） */
  '/fixes': ({ checks, brand, spec }: { checks: ReviewCheck[]; brand: Brand; spec: PromptSpec }) => planFixes(checks, brand, spec),

  /** 每段文字中，海報字型沒有的字（系統狀態檢查品牌設定檔用） */
  '/glyphs': ({ texts }: { texts: unknown }) => {
    ensure(isStrings(texts), 'texts 必須是字串陣列');
    return { missing: texts.map(missingGlyphs) };
  },

  '/sim/brief': ({ brand, product, text }: { brand: Brand; product: Product | null; text: string }) =>
    parseBrief(text, brand, product),

  '/sim/prompt': (b: {
    jobId: string; round: number; brand: Brand; product: Product; brief: ParsedBrief; templateId: TemplateId;
    engine: Engine; seed: number; ragRefs: string[]; fixes: CheckId[]; flawed: boolean;
  }) => {
    const spec = buildPromptSpec({ ...b, template: getTemplate(b.templateId) });
    return b.flawed ? applyFlaws(spec, FLAWS, b.brand) : spec;
  },

  '/sim/review': ({ spec, brand, variant, seed }: { spec: PromptSpec; brand: Brand; variant: number; seed: number }) => {
    const { checks, score, passed } = reviewRender(spec, brand, variant, seed);
    return { checks, score, passed };
  },

  '/sim/fixes': ({ checks, brand, spec }: { checks: ReviewCheck[]; brand: Brand; spec: PromptSpec }) =>
    planFixes(checks, brand, spec),
};

/** 執行路徑對應的 handler；回傳值可能是 Promise，由伺服器 await */
export function handle(path: string, body: unknown): unknown {
  const handler = HANDLERS[path];
  if (!handler) throw new UnknownRoute(`Unknown route: ${path}`);
  return handler(body as never);
}
