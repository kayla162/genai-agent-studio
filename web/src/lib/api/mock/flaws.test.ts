import { describe, it, expect } from 'vitest';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from './data';
import { applyFlaws, FLAWS } from './flaws';

describe('applyFlaws', () => {
  it('applies every flaw without mutating the input', () => {
    const spec = cleanSpec();
    const bad = applyFlaws(spec, FLAWS);
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
    expect(bad.copy.disclaimer).toBe('活動期間 2026/10/15–11/15｜數量有限，售完為止');
    const logo = bad.layout.find((b) => b.id === 'logo')!;
    const head = bad.layout.find((b) => b.id === 'headline')!;
    expect(logo.bbox[1] + logo.bbox[3]).toBeGreaterThan(head.bbox[1]);
    expect(bad.injection.params.find((p) => p.label === 'positive_prompt')?.value).toContain('vivid saturated colors');
  });

  it('applies only the requested flaws', () => {
    const bad = applyFlaws(cleanSpec(), ['bannedCopy']);
    expect(bad.palette).toEqual(SELUNE.palette);
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('throws for brands without flaw data', () => {
    expect(() => applyFlaws({ ...cleanSpec(), brandId: 'nope' }, ['bannedCopy'])).toThrow('No flaw data');
  });
});
