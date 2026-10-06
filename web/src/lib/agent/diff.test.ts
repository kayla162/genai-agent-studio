import { describe, it, expect } from 'vitest';
import { makeSpec } from '@/test/fixtures';
import { diffSpecs, inlineDiff } from './diff';

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

  it('shows rewritten headline and features', () => {
    const b = makeSpec();
    b.copy.features = ['改善外觀暗沉'];
    expect(diffSpecs(makeSpec(), b)).toEqual([
      { path: 'copy.features', before: '5重玻尿酸、神經醯胺、無香精', after: '改善外觀暗沉' },
    ]);
  });
});

describe('inlineDiff', () => {
  it('keeps the common prefix and suffix and isolates the change', () => {
    expect(inlineDiff('lowres, blurry', 'lowres, blurry, neon')).toEqual({ prefix: 'lowres, blurry', removed: '', added: ', neon', suffix: '' });
    expect(inlineDiff('[["logo",101,38,374]]', '[["logo",101,90,374]]')).toEqual({
      prefix: '[["logo",101,', removed: '38', added: '90', suffix: ',374]]',
    });
  });

  it('does not let the prefix and suffix overlap', () => {
    expect(inlineDiff('aa', 'aaa')).toEqual({ prefix: 'aa', removed: '', added: 'a', suffix: '' });
    expect(inlineDiff('same', 'same')).toEqual({ prefix: 'same', removed: '', added: '', suffix: '' });
  });
});
