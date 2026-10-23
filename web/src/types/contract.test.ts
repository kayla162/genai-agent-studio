import { describe, it, expect } from 'vitest';
import { TEMPLATE_IDS, LAYOUT_ELEMENT_IDS, CHECK_IDS, TONES } from './contract';

const unique = (xs: readonly string[]) => new Set(xs).size === xs.length;

describe('contract constants', () => {
  it('lists the 5 channel templates from the spec', () => {
    expect(TEMPLATE_IDS).toEqual(['ecom-main', 'scene', 'ig-post', 'story', 'banner']);
  });

  it('has 8 layout elements, 11 checks and 4 tones, all unique', () => {
    expect(LAYOUT_ELEMENT_IDS).toHaveLength(8);
    expect(CHECK_IDS).toHaveLength(11);
    expect(TONES).toHaveLength(4);
    expect(unique(LAYOUT_ELEMENT_IDS) && unique(CHECK_IDS) && unique(TONES)).toBe(true);
  });
});
