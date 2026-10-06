import { describe, it, expect } from 'vitest';
import { visLen, truncate } from './text';
import { truncate as aliasedTruncate } from '@/lib/core/text';

describe('text utils', () => {
  it('visLen counts CJK as 1em, spaces as 0.3em, others as 0.58em', () => {
    expect(visLen('一夜')).toBe(2);
    expect(visLen('72H')).toBeCloseTo(1.74);
    expect(visLen('a b')).toBeCloseTo(1.46);
  });

  it('truncate adds an ellipsis only when the text is longer than n', () => {
    expect(truncate('冷萃咖啡宣傳海報', 4)).toBe('冷萃咖啡…');
    expect(truncate('冷萃', 4)).toBe('冷萃');
  });

  it('resolves the @/* path alias', () => {
    expect(aliasedTruncate).toBe(truncate);
  });
});
