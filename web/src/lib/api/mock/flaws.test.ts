import { describe, it, expect } from 'vitest';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from './data';
import { applyFlaws, FLAWS } from './flaws';

describe('applyFlaws', () => {
  it('applies every flaw without mutating the input', () => {
    const spec = cleanSpec();
    const bad = applyFlaws(spec, FLAWS, SELUNE);
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
    const bad = applyFlaws(cleanSpec(), ['bannedCopy'], SELUNE);
    expect(bad.palette).toEqual(SELUNE.palette);
    expect(bad.copy.subhead).toBe('7天根治暗沉・醫療級修護');
  });

  it('derives the flaws of other brands from their own palette and banned words', () => {
    const blue = { ...SELUNE, id: 'my-brand', palette: { ...SELUNE.palette, primary: '#1E6FD9' as const }, bannedWords: ['根治', '治療', '保證有效'] };
    const bad = applyFlaws(cleanSpec(), FLAWS, blue);
    // 兩組示範偏色中，與品牌主色差最多的一組
    expect(bad.palette.primary).toBe('#E0458A');
    expect(bad.copy.subhead).toBe('根治・治療');
    const pink = { ...blue, palette: { ...blue.palette, primary: '#E0458A' as const } };
    expect(applyFlaws(cleanSpec(), ['offPalette'], pink).palette.primary).toBe('#1E88E5');
  });

  it('leaves the subhead alone when the brand has no banned words', () => {
    const plain = { ...SELUNE, id: 'my-brand', bannedWords: [] };
    expect(applyFlaws(cleanSpec(), ['bannedCopy'], plain).copy.subhead).toBe(cleanSpec().copy.subhead);
  });
});
