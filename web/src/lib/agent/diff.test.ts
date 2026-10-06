import { describe, it, expect } from 'vitest';
import { makeSpec } from '@/test/fixtures';
import { diffSpecs } from './diff';

describe('diffSpecs', () => {
  it('returns nothing for identical specs', () => {
    expect(diffSpecs(makeSpec(), makeSpec())).toEqual([]);
  });

  it('lists changed fields in a fixed order with readable values', () => {
    const b = makeSpec();
    b.palette = { ...b.palette, primary: '#E0458A' };
    b.copy.subhead = '7天根治暗沉・醫療級修護';
    b.layout.find((x) => x.id === 'logo')!.bbox[1] = 171;
    expect(diffSpecs(makeSpec(), b)).toEqual([
      { path: 'palette.primary', before: '#B76E79', after: '#E0458A' },
      { path: 'layout[logo].bbox', before: '[101, 90, 374, 81]', after: '[101, 171, 374, 81]' },
      { path: 'copy.subhead', before: '7天感受透亮光采・專業修護配方*', after: '7天根治暗沉・醫療級修護' },
    ]);
  });
});
