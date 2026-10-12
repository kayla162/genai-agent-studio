import type { Brand, Copy, Product, Render } from '@/types/contract';
import { backgroundSvg, svgDataUrl } from './art';
import { fontStacks, productImage } from './assets';
import { boxMap } from './layout';
import { paintScene, type PaintAssets } from './paint';
import { composePoster, type PosterScene, type TextOp } from './scene';

/**
 * 瀏覽器端：準備圖片與字型後把海報畫到 Canvas。預覽與匯出共用。
 * 只能在 client component 的 effect 或事件處理中呼叫（需要 document、Image、Canvas）。
 */

export interface PosterInput {
  render: Render;
  /** 使用者編輯後的文案；不改文案時傳 render.spec.copy */
  copy: Copy;
  /** 商品已刪除時為 null（只畫背景與文字） */
  product: Product | null;
  brand: Brand;
}

export interface PreparedPoster { scene: PosterScene; assets: PaintAssets }

const imageCache = new Map<string, Promise<HTMLImageElement>>();

export function loadImage(src: string): Promise<HTMLImageElement> {
  const hit = imageCache.get(src);
  if (hit) return hit;
  const p = new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('圖片載入失敗'));
    img.src = src;
  });
  p.catch(() => imageCache.delete(src));
  imageCache.set(src, p);
  // 只保留最近 80 張，避免 data URL 佔滿記憶體
  if (imageCache.size > 80) imageCache.delete(imageCache.keys().next().value!);
  return p;
}

async function ensureFonts(scene: PosterScene, fonts: PaintAssets['fonts']) {
  if (typeof document === 'undefined' || !document.fonts) return;
  const texts = scene.ops.flatMap((op): TextOp[] =>
    op.kind === 'text' ? [op] : op.kind === 'badge' ? op.texts : op.kind === 'logo' && op.wordmark ? [op.wordmark] : [],
  );
  const sample = (role: 'headline' | 'body') => texts.filter((t) => t.role === role).map((t) => t.text).join('') || 'A';
  await Promise.all([
    document.fonts.load(`900 40px ${fonts.headline}`, sample('headline')),
    document.fonts.load(`500 40px ${fonts.body}`, sample('body')),
  ]).catch(() => undefined);
}

export async function preparePoster({ render, copy, product, brand }: PosterInput): Promise<PreparedPoster> {
  const spec = render.spec;
  const scene = composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy, brand });
  const bg = render.background;
  const bgSrc = bg.kind === 'procedural'
    ? svgDataUrl(backgroundSvg({
      width: spec.canvas.width, height: spec.canvas.height, palette: bg.palette, seed: bg.seed, style: bg.style,
      focus: boxMap(spec.layout).product,
    }))
    : bg.url;
  const prod = product ? productImage(product, brand) : null;
  const fonts = fontStacks(brand);
  const [background, productImg, logoImg] = await Promise.all([
    loadImage(bgSrc),
    prod ? loadImage(prod.src).catch(() => null) : Promise.resolve(null),
    // Logo 圖檔載入失敗時改畫標誌圖形與字標
    brand.logo ? loadImage(brand.logo.url).catch(() => null) : Promise.resolve(null),
    ensureFonts(scene, fonts),
  ]);
  return {
    scene,
    assets: {
      background,
      product: productImg && prod
        ? { image: productImg, width: productImg.naturalWidth || 500, height: productImg.naturalHeight || 800, blend: prod.blend }
        : null,
      // 沒有固有尺寸的 SVG 以 3:1 計算
      logo: logoImg ? { image: logoImg, width: logoImg.naturalWidth || 300, height: logoImg.naturalHeight || 100 } : null,
      fonts,
    },
  };
}

/** 畫到指定寬度（像素）的 Canvas；高度依模板比例 */
export function paintPoster(canvas: HTMLCanvasElement, { scene, assets }: PreparedPoster, pixelWidth: number): void {
  const scale = pixelWidth / scene.width;
  canvas.width = Math.round(pixelWidth);
  canvas.height = Math.round(scene.height * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, scene.width, scene.height);
  paintScene(ctx, scene, assets);
}

/** 匯出：以模板原始尺寸輸出 PNG */
export async function posterBlob(input: PosterInput): Promise<Blob> {
  const prepared = await preparePoster(input);
  const canvas = document.createElement('canvas');
  paintPoster(canvas, prepared, prepared.scene.width);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('PNG 輸出失敗'))), 'image/png'),
  );
}
