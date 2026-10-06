import type { Brand, Copy, ReviewCheck, Render } from '@/types/contract';
import { runRuleChecks } from './rules';

/**
 * 文字編輯器改了文案後重新跑規則型審查（VLM 不重跑，沿用生成時的結果）。
 * 偵測主色沿用該張背景的主色，所以色差結果與生成時一致。
 */
export function recheckCopy(render: Render, brand: Brand, copy: Copy): ReviewCheck[] {
  return runRuleChecks({ brand, spec: { ...render.spec, copy }, measuredPrimary: render.spec.palette.primary });
}

/** 由文案造成、匯出前必須修正的問題（目前只有禁用詞） */
export const copyBlockers = (checks: ReviewCheck[]): ReviewCheck[] =>
  checks.filter((c) => c.id === 'banned_words' && c.status === 'fail');
