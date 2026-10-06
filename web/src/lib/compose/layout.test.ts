import { describe, it, expect } from 'vitest';
import { CHANNEL_TEMPLATES, getTemplate } from './templates';
import { computeLayout, boxMap, fitFontSize } from './layout';
import { intersectionArea, isInside, areaRatio, verticalGap, toRect } from '@/lib/core/geometry';

describe('channel templates', () => {
  it('has the 5 templates from the spec with exact output sizes', () => {
    expect(CHANNEL_TEMPLATES.map((t) => [t.id, t.width, t.height])).toEqual([
      ['ecom-main', 1600, 1600],
      ['scene', 2048, 1536],
      ['ig-post', 1440, 1800],
      ['story', 1152, 2048],
      ['banner', 2048, 1152],
    ]);
    expect(getTemplate('story').ratio).toBe('9:16');
    expect(() => getTemplate('nope' as never)).toThrow('Unknown template');
  });
});

describe.each(CHANNEL_TEMPLATES)('computeLayout($id)', (t) => {
  const layout = computeLayout(t);
  const B = boxMap(layout);

  it('returns 8 boxes inside the canvas', () => {
    expect(layout).toHaveLength(8);
    for (const b of layout) expect(isInside(toRect(b.bbox), t.width, t.height)).toBe(true);
  });

  it('has no overlapping boxes', () => {
    for (let i = 0; i < layout.length; i++)
      for (let j = i + 1; j < layout.length; j++)
        expect(intersectionArea(toRect(layout[i].bbox), toRect(layout[j].bbox)), `${layout[i].id} vs ${layout[j].id}`).toBe(0);
  });

  it('keeps the logo clear of the headline by at least half the logo height', () => {
    expect(verticalGap(B.logo, B.headline)).toBeGreaterThanOrEqual(Math.round(B.logo.h * 0.5));
  });

  it('draws the badge as a near-square and keeps product/whitespace ratios valid', () => {
    expect(Math.abs(B.badge.w - B.badge.h)).toBeLessThanOrEqual(2);
    const prod = areaRatio(B.product, t.width, t.height);
    expect(prod).toBeGreaterThanOrEqual(0.2);
    expect(prod).toBeLessThanOrEqual(0.5);
    const used = Object.values(B).reduce((s, r) => s + areaRatio(r, t.width, t.height), 0);
    expect(1 - used).toBeGreaterThanOrEqual(0.4);
  });
});

describe('fitFontSize', () => {
  it('is limited by height for two lines and by width for long lines', () => {
    expect(fitFontSize(['一夜溫柔修護', '醒來透亮發光'], { w: 900, h: 300 })).toBe(125);
    expect(fitFontSize(['一二三四五六七八九十'], { w: 500, h: 300 })).toBe(50);
  });
});
