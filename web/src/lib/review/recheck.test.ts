import { describe, it, expect } from 'vitest';
import type { Render } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { applyFlaws } from '@/lib/api/mock/flaws';
import { cleanSpec } from '@/test/fixtures';
import { copyBlockers, recheckCopy } from './recheck';

const renderOf = (spec = cleanSpec()): Render => ({
  id: 'r1', jobId: 'job_t', round: 2, templateId: spec.templateId, variant: 0,
  background: { kind: 'procedural', seed: 1, palette: spec.palette, style: 'selune' }, spec, score: 96, passed: true, checks: [],
});

describe('recheckCopy', () => {
  it('passes the original copy of a clean render', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, r.spec.copy);
    expect(checks.map((c) => c.status)).toEqual(['pass', 'pass', 'pass', 'pass', 'pass', 'pass', 'pass']);
    expect(copyBlockers(checks)).toEqual([]);
  });

  it('blocks export when the edited copy contains a banned word', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, { ...r.spec.copy, subhead: '7天根治暗沉' });
    expect(copyBlockers(checks).map((c) => c.target)).toEqual(['subhead']);
  });

  it('warns but does not block when the disclaimer is removed', () => {
    const r = renderOf();
    const checks = recheckCopy(r, SELUNE, { ...r.spec.copy, disclaimer: '' });
    expect(checks.find((c) => c.id === 'disclaimer')!.status).toBe('warn');
    expect(copyBlockers(checks)).toEqual([]);
  });

  it('keeps the color result of an off-brand render', () => {
    const r = renderOf(applyFlaws(cleanSpec(), ['offPalette']));
    expect(recheckCopy(r, SELUNE, r.spec.copy).find((c) => c.id === 'color_delta')!.status).toBe('fail');
  });
});
