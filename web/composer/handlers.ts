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

/** 找不到路徑（伺服器回 404） */
export class UnknownRoute extends Error {}

type Handler = (body: never) => unknown;

/**
 * 後端呼叫的 TypeScript 邏輯：版型，以及模擬模式沿用的 mock 行為（/sim/*）。
 * 每個 handler 都是純函式：輸入與輸出都是合約的 JSON。
 */
const HANDLERS: Record<string, Handler> = {
  '/layout': ({ templateId }: { templateId: TemplateId }) => computeLayout(getTemplate(templateId)),

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

export function handle(path: string, body: unknown): unknown {
  const handler = HANDLERS[path];
  if (!handler) throw new UnknownRoute(`Unknown route: ${path}`);
  return handler(body as never);
}
