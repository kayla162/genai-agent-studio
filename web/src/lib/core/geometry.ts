import type { BBox } from '@/types/contract';

export interface Rect { x: number; y: number; w: number; h: number }

export const toRect = ([x, y, w, h]: BBox): Rect => ({ x, y, w, h });

export function intersectionArea(a: Rect, b: Rect): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

/** 交集面積 ÷ 較小的那個框的面積 */
export function overlapRatio(a: Rect, b: Rect): number {
  const smaller = Math.min(a.w * a.h, b.w * b.h);
  return smaller > 0 ? intersectionArea(a, b) / smaller : 0;
}

export const areaRatio = (r: Rect, W: number, H: number): number => (r.w * r.h) / (W * H);

/** below 的上緣到 above 的下緣之距離；負值代表重疊 */
export const verticalGap = (above: Rect, below: Rect): number => below.y - (above.y + above.h);

export const isInside = (r: Rect, W: number, H: number): boolean =>
  r.x >= 0 && r.y >= 0 && r.x + r.w <= W && r.y + r.h <= H;
