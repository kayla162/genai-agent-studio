import { LAYOUT_ELEMENT_IDS } from '@/types/contract';
import type { ChannelTemplate, LayoutBox, LayoutElementId, TemplateId } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { visLen } from '@/lib/core/text';

type NormBox = [x: number, y: number, w: number, h: number];

/** 各模板版型，以畫布比例表示 [x, y, w, h]。直式文字在上、商品在下；橫式文字在左、商品在右。 */
export const LAYOUT_PRESETS: Record<TemplateId, Record<LayoutElementId, NormBox>> = {
  'ecom-main': {
    logo: [0.06, 0.06, 0.22, 0.045], headline: [0.06, 0.15, 0.48, 0.2], subhead: [0.06, 0.375, 0.46, 0.035],
    features: [0.06, 0.43, 0.46, 0.04], product: [0.55, 0.1, 0.4, 0.82], badge: [0.06, 0.53, 0.17, 0.17],
    price: [0.26, 0.555, 0.28, 0.12], disclaimer: [0.06, 0.94, 0.88, 0.025],
  },
  scene: {
    logo: [0.05, 0.07, 0.18, 0.055], headline: [0.05, 0.17, 0.45, 0.22], subhead: [0.05, 0.415, 0.45, 0.04],
    features: [0.05, 0.48, 0.45, 0.05], product: [0.55, 0.08, 0.4, 0.84], badge: [0.05, 0.58, 0.13, 0.173],
    price: [0.21, 0.6, 0.28, 0.14], disclaimer: [0.05, 0.93, 0.45, 0.03],
  },
  'ig-post': {
    logo: [0.07, 0.05, 0.26, 0.045], headline: [0.07, 0.12, 0.6, 0.16], subhead: [0.07, 0.295, 0.55, 0.035],
    features: [0.07, 0.345, 0.5, 0.04], product: [0.44, 0.4, 0.5, 0.51], badge: [0.07, 0.47, 0.24, 0.192],
    price: [0.07, 0.7, 0.36, 0.11], disclaimer: [0.07, 0.935, 0.86, 0.025],
  },
  story: {
    logo: [0.08, 0.04, 0.34, 0.04], headline: [0.08, 0.105, 0.84, 0.13], subhead: [0.08, 0.25, 0.84, 0.03],
    features: [0.08, 0.295, 0.84, 0.035], product: [0.12, 0.35, 0.52, 0.41], badge: [0.64, 0.4, 0.28, 0.1575],
    price: [0.08, 0.79, 0.84, 0.1], disclaimer: [0.08, 0.945, 0.84, 0.022],
  },
  banner: {
    logo: [0.04, 0.08, 0.15, 0.07], headline: [0.04, 0.21, 0.42, 0.26], subhead: [0.04, 0.5, 0.42, 0.05],
    features: [0.04, 0.58, 0.42, 0.06], product: [0.52, 0.06, 0.36, 0.88], badge: [0.04, 0.7, 0.09, 0.16],
    price: [0.15, 0.7, 0.3, 0.17], disclaimer: [0.04, 0.92, 0.44, 0.04],
  },
};

const Z_INDEX: Partial<Record<LayoutElementId, number>> = { product: 1, badge: 3 };

export function computeLayout(t: ChannelTemplate): LayoutBox[] {
  const preset = LAYOUT_PRESETS[t.id];
  return LAYOUT_ELEMENT_IDS.map((id): LayoutBox => {
    const [x, y, w, h] = preset[id];
    return {
      id,
      bbox: [Math.round(x * t.width), Math.round(y * t.height), Math.round(w * t.width), Math.round(h * t.height)],
      z: Z_INDEX[id] ?? 2,
    };
  });
}

export function boxMap(layout: LayoutBox[]): Record<LayoutElementId, Rect> {
  return Object.fromEntries(
    layout.map((b) => [b.id, { x: b.bbox[0], y: b.bbox[1], w: b.bbox[2], h: b.bbox[3] }]),
  ) as Record<LayoutElementId, Rect>;
}

/** 讓多行文字同時符合框的高度與寬度的最大字級（px） */
export function fitFontSize(lines: string[], box: { w: number; h: number }, lineHeight = 1.2): number {
  const widest = Math.max(...lines.map(visLen), 1e-6);
  return Math.min(box.h / (lines.length * lineHeight), box.w / widest);
}
