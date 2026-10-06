import type { Brand, PromptSpec, ReviewCheck } from '@/types/contract';
import { mulberry32 } from '@/lib/core/num';
import { mixHex } from '@/lib/review/color';
import { runRuleChecks, scoreChecks } from '@/lib/review/rules';
import { mockVlmChecks } from './vlm';

export interface ReviewResult { checks: ReviewCheck[]; score: number; passed: boolean; measuredPrimary: string }

/** 規則型檢查 + 模擬 VLM，再計分。seed 決定「偵測主色」的微小偏移與分數抖動。 */
export function reviewRender(spec: PromptSpec, brand: Brand, variant: number, seed: number): ReviewResult {
  const rng = mulberry32(seed);
  const measuredPrimary = mixHex(spec.palette.primary, '#ffffff', 0.01 + rng() * 0.02);
  const checks = [...runRuleChecks({ brand, spec, measuredPrimary }), ...mockVlmChecks(spec, brand, variant)];
  const { score, passed } = scoreChecks(checks, Math.floor(rng() * 4));
  return { checks, score, passed, measuredPrimary };
}
