import type { PromptSpec } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { boxMap } from './layout';
import { containBottom } from './paint';

/*
 * ComfyUI 生成背景用的商品底圖（Plan 7 規格 §4.3）：生成解析度與模板尺寸的換算。
 * 生成的圖以 cover 方式放大（等比、至少填滿模板），再置中裁切成模板尺寸；底圖上的商品位置換算回模板後，
 * 與 paint 畫商品的矩形（containBottom）相同，最後疊上的原始去背圖才會剛好蓋住生成時的商品。
 */

/** 各模板比例的 SDXL 生成尺寸（約 100 萬像素、邊長為 64 的倍數） */
export const GENERATION_SIZES: Record<string, { width: number; height: number }> = {
  '1:1': { width: 1024, height: 1024 },
  '4:3': { width: 1152, height: 896 },
  '4:5': { width: 896, height: 1152 },
  '9:16': { width: 768, height: 1344 },
  '16:9': { width: 1344, height: 768 },
};

/** 遮罩上商品（保留區域）向外擴張的像素，以生成解析度計算（實驗決定） */
export const PLATE_MASK_GROW = 8;

export function generationSize(ratio: string): { width: number; height: number } {
  const size = GENERATION_SIZES[ratio];
  if (!size) throw new Error(`沒有 ${ratio} 的生成尺寸`);
  return size;
}

export interface PlateGeometry {
  /** 生成尺寸 */
  width: number;
  height: number;
  /** 生成的圖放大到模板時的倍率（cover：兩邊都至少填滿） */
  scale: number;
  /** 放大後置中裁切的左上角位移（模板像素） */
  crop: { x: number; y: number };
  /** 商品在生成尺寸上的矩形；沒有商品時為 null */
  productRect: Rect | null;
}

/**
 * 生成尺寸、放大倍率與裁切，以及商品在生成圖上的位置。
 * product：商品圖的固有尺寸（與 paint 相同，以 containBottom 放進商品框）；'box' 為整個商品框（尺寸不明時）；
 * null 為沒有商品（已刪除）。
 */
export function plateGeometry(
  spec: Pick<PromptSpec, 'canvas' | 'layout'>, product: { width: number; height: number } | 'box' | null,
): PlateGeometry {
  const { width: W, height: H } = spec.canvas;
  const { width, height } = generationSize(spec.canvas.ratio);
  const scale = Math.max(W / width, H / height);
  const crop = { x: (width * scale - W) / 2, y: (height * scale - H) / 2 };
  const box = boxMap(spec.layout).product;
  const target = product === null ? null : product === 'box' ? box : containBottom(box, product.width, product.height);
  const productRect = target && {
    x: (target.x + crop.x) / scale, y: (target.y + crop.y) / scale, w: target.w / scale, h: target.h / scale,
  };
  return { width, height, scale, crop, productRect };
}

/** 生成尺寸上的矩形換算回模板像素（plateGeometry 的反向） */
export function toTemplate(g: Pick<PlateGeometry, 'scale' | 'crop'>, r: Rect): Rect {
  return { x: r.x * g.scale - g.crop.x, y: r.y * g.scale - g.crop.y, w: r.w * g.scale, h: r.h * g.scale };
}

/** 二值遮罩（1 為保留）向外擴張 r 像素（正方形的鄰域）；回傳新的陣列 */
export function dilateMask(mask: Uint8Array, width: number, height: number, r: number): Uint8Array {
  if (r <= 0) return mask.slice();
  // 先橫向再縱向取最大值：與 (2r+1)×(2r+1) 的正方形相同
  const row = new Uint8Array(mask.length);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let on = 0;
      for (let k = Math.max(0, x - r); k <= Math.min(width - 1, x + r) && !on; k++) on = mask[y * width + k];
      row[y * width + x] = on;
    }
  }
  const out = new Uint8Array(mask.length);
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) {
      let on = 0;
      for (let k = Math.max(0, y - r); k <= Math.min(height - 1, y + r) && !on; k++) on = row[k * width + x];
      out[y * width + x] = on;
    }
  }
  return out;
}
