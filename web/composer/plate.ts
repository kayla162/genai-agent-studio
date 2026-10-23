// ComfyUI 生成背景用的商品底圖與遮罩（Plan 7 規格 §4.3）：worker 上傳到 ComfyUI，生成時商品的位置與最後疊上的
// 原始去背圖相同（plateGeometry 與 paint 共用 containBottom）。
import { createCanvas, type Image } from '@napi-rs/canvas';
import type { Brand, Product, PromptSpec } from '@/types/contract';
import type { Rect } from '@/lib/core/geometry';
import { dilateMask, PLATE_MASK_GROW, plateGeometry } from '@/lib/compose/plate';
import { loadProduct, type PosterImages } from './poster';

/** 底圖上商品以外的中性灰 */
export const PLATE_GREY = [128, 128, 128];
/** 上傳的商品還沒去背（以原圖合成）時的警告：遮罩保留整個照片矩形 */
export const NOT_CUT_OUT = '商品尚未去背，背景依外框生成';
/** 去背圖的 alpha ≥ 這個值算是商品 */
const OPAQUE = 128;

export interface PlateInput {
  spec: Pick<PromptSpec, 'canvas' | 'layout'>;
  /** 商品已刪除時為 null（整張重繪） */
  product: Product | null;
  brand: Brand;
  /** 與 /render 相同：上傳商品的去背圖或原圖（base64） */
  images: Pick<PosterImages, 'product'>;
}

export interface PlateResult {
  /** 生成尺寸 */
  width: number;
  height: number;
  /** 生成的圖放大到模板的倍率與置中裁切的位移（模板像素） */
  scale: number;
  crop: { x: number; y: number };
  /** 商品在生成尺寸上的矩形；沒有商品時為 null */
  productRect: Rect | null;
  /** 中性灰畫布加上商品（PNG，base64） */
  plate: string;
  /** 重繪範圍：白色重繪、黑色保留（商品向外擴張 grow 像素；PNG，base64） */
  mask: string;
  /** 商品還沒去背時的說明；其他情況為 null */
  warning: string | null;
}

/** 依生成尺寸繪製底圖與遮罩。grow 為遮罩上商品向外擴張的像素（預設 PLATE_MASK_GROW） */
export async function renderPlate({ spec, product, brand, images }: PlateInput, grow = PLATE_MASK_GROW): Promise<PlateResult> {
  const loaded = await loadProduct(product, brand, images.product);
  const size = loaded ? { width: loaded.image.naturalWidth || 500, height: loaded.image.naturalHeight || 800 } : null;
  const g = plateGeometry(spec, size);
  const { width, height } = g;

  const plate = createCanvas(width, height);
  const pctx = plate.getContext('2d');
  pctx.fillStyle = `rgb(${PLATE_GREY.join(',')})`;
  pctx.fillRect(0, 0, width, height);

  let keep: Uint8Array = new Uint8Array(width * height);
  const r = g.productRect;
  if (loaded && r) {
    pctx.drawImage(loaded.image, r.x, r.y, r.w, r.h);
    keep = loaded.blend === 'normal' ? alphaMask(loaded.image, r, width, height) : rectMask(r, width, height);
  }
  const mask = maskPng(dilateMask(keep, width, height, grow), width, height);
  return {
    width, height, scale: g.scale, crop: g.crop, productRect: r,
    plate: (await plate.encode('png')).toString('base64'),
    mask: (await mask.encode('png')).toString('base64'),
    warning: loaded && loaded.blend !== 'normal' ? NOT_CUT_OUT : null,
  };
}

/** 去背圖（或示範商品的 SVG）畫在透明畫布上，alpha ≥ OPAQUE 的像素為商品 */
function alphaMask(image: Image, r: Rect, width: number, height: number): Uint8Array {
  const ctx = createCanvas(width, height).getContext('2d');
  ctx.drawImage(image, r.x, r.y, r.w, r.h);
  const { data } = ctx.getImageData(0, 0, width, height);
  const keep = new Uint8Array(width * height);
  for (let i = 0; i < keep.length; i++) keep[i] = data[i * 4 + 3] >= OPAQUE ? 1 : 0;
  return keep;
}

/** 整個照片矩形（含部分覆蓋的邊緣像素）為商品 */
function rectMask(r: Rect, width: number, height: number): Uint8Array {
  const keep = new Uint8Array(width * height);
  const [x0, x1] = [Math.max(0, Math.floor(r.x)), Math.min(width, Math.ceil(r.x + r.w))];
  const [y0, y1] = [Math.max(0, Math.floor(r.y)), Math.min(height, Math.ceil(r.y + r.h))];
  for (let y = y0; y < y1; y++) keep.fill(1, y * width + x0, y * width + x1);
  return keep;
}

/** 保留的像素畫成黑色，其餘白色 */
function maskPng(keep: Uint8Array, width: number, height: number) {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(width, height);
  for (let i = 0; i < keep.length; i++) {
    const v = keep[i] ? 0 : 255;
    img.data.set([v, v, v, 255], i * 4);
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}
