import { describe, it, expect } from 'vitest';
import { toRect, intersectionArea, overlapRatio, areaRatio, verticalGap, isInside } from './geometry';

const a = { x: 0, y: 0, w: 10, h: 10 };

describe('geometry', () => {
  it('computes intersection area; touching edges do not intersect', () => {
    expect(intersectionArea(a, { x: 5, y: 5, w: 10, h: 10 })).toBe(25);
    expect(intersectionArea(a, { x: 10, y: 0, w: 5, h: 5 })).toBe(0);
    expect(intersectionArea(a, { x: 20, y: 20, w: 5, h: 5 })).toBe(0);
  });

  it('overlapRatio is intersection over the smaller area', () => {
    expect(overlapRatio(a, { x: 5, y: 5, w: 10, h: 10 })).toBe(0.25);
    expect(overlapRatio(a, { x: 2, y: 2, w: 2, h: 2 })).toBe(1);
  });

  it('areaRatio, verticalGap, isInside, toRect', () => {
    expect(areaRatio(a, 20, 20)).toBe(0.25);
    expect(verticalGap(a, { x: 0, y: 14, w: 5, h: 5 })).toBe(4);
    expect(verticalGap(a, { x: 0, y: 6, w: 5, h: 5 })).toBe(-4);
    expect(isInside(a, 10, 10)).toBe(true);
    expect(isInside({ x: 5, y: 0, w: 10, h: 5 }, 10, 10)).toBe(false);
    expect(toRect([1, 2, 3, 4])).toEqual({ x: 1, y: 2, w: 3, h: 4 });
  });
});
