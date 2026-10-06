import { describe, it, expect } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { runRuleChecks } from '@/lib/review/rules';
import { makeSpec } from '@/test/fixtures';
import { planFixes } from './fixes';

const vlm = (id: ReviewCheck['id'], status: ReviewCheck['status']): ReviewCheck => ({
  id, name: id, kind: 'vlm', rule: '', value: '', status, target: null, ragRef: null,
});

describe('planFixes', () => {
  it('maps failed checks to fixes, using the brand replacement table for copy', () => {
    const spec = makeSpec();
    spec.copy.subhead = '7天根治暗沉・醫療級修護';
    const checks = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#E0458A' });
    const fixes = planFixes(checks, SELUNE, spec);
    expect(fixes.map((f) => f.title)).toEqual(['文案改寫', '色彩修正']);
    expect(fixes[0]).toEqual({
      checkId: 'banned_words', title: '文案改寫',
      desc: '依合規替代用語改寫：「根治」→「改善外觀」、「醫療級」→「專業配方」',
    });
  });

  it('dedupes fixes with the same title and ignores passing checks', () => {
    const spec = makeSpec();
    spec.copy.subhead = '保證有效';
    const fixes = planFixes(
      [vlm('banned_words', 'fail'), vlm('vlm_exaggeration', 'fail'), vlm('vlm_quality', 'pass')],
      SELUNE, spec,
    );
    expect(fixes).toEqual([{ checkId: 'banned_words', title: '文案改寫', desc: '依合規替代用語改寫：「保證有效」→刪除' }]);
    expect(planFixes([vlm('vlm_quality', 'pass')], SELUNE, spec)).toEqual([]);
  });
});
