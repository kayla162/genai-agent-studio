import type {
  Brand, CheckId, Engine, ParsedBrief, Product, PromptSpec, ReviewCheck, TemplateId,
} from '@/types/contract';
import { planFixes } from '@/lib/agent/fixes';
import { buildPromptSpec } from '@/lib/agent/prompt';
import { parseBrief } from '@/lib/api/mock/brief';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { reviewRender } from '@/lib/api/mock/review';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { contentVlmChecks } from '@/lib/review/vlm';
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

/** live 模式的審查：7 項規則加 3 項依內容判斷的 VLM 檢查，分數不加隨機抖動 */
function reviewPoster({ spec, brand, measuredPrimary }: {
  spec: PromptSpec; brand: Brand; measuredPrimary: string | null;
}): { checks: ReviewCheck[]; score: number; passed: boolean } {
  if (measuredPrimary !== null && !(typeof measuredPrimary === 'string' && HEX.test(measuredPrimary))) {
    throw new Error(`measuredPrimary 必須是 #RRGGBB 或 null：${JSON.stringify(measuredPrimary)}`);
  }
  const checks = [...runRuleChecks({ brand, spec, measuredPrimary }), ...contentVlmChecks(spec, brand)];
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
