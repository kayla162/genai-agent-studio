// composer 在伺服器端繪製審查用海報：流程與瀏覽器的 render.ts（preparePoster → paintPoster）相同，
// 版面與繪製直接沿用 scene.ts 與 paint.ts，只把載圖與 Canvas 換成 @napi-rs/canvas。
import { createCanvas, loadImage, type Image, type SKRSContext2D } from '@napi-rs/canvas';
import type { Brand, Product, PromptSpec, Render } from '@/types/contract';
import { backgroundSvg } from '@/lib/compose/art';
import { fontStacks, productImage } from '@/lib/compose/assets';
import { boxMap } from '@/lib/compose/layout';
import { paintScene, type PaintAssets } from '@/lib/compose/paint';
import { composePoster } from '@/lib/compose/scene';
import { BACKGROUND_MEASURE, measureBackgroundPalette, type BackgroundPalette } from '@/lib/review/background';
import { measurePrimary, type MeasuredPrimary } from '@/lib/review/measure';

/** worker 讀好的圖檔（base64）。composer 不讀任何資料夾 */
export interface PosterImages {
  /** 上傳商品的去背圖或原圖，blend 規則與前端 productImage 相同；示範商品（向量素材）與沒有商品時為 null */
  product: { base64: string; blend: 'normal' | 'multiply' } | null;
  /** 品牌的 Logo 圖檔；null 時畫向量標誌與字標（與前端相同） */
  logo: { base64: string } | null;
  /** 背景為 url 時的圖檔；程式產生的背景（procedural）不需要 */
  background?: { base64: string } | null;
}

export interface RenderPosterInput {
  render: Render;
  /** 商品已刪除時為 null（只畫背景與文字） */
  product: Product | null;
  brand: Brand;
  images: PosterImages;
}

export interface RenderedPoster {
  /** 模板原始尺寸的 PNG */
  png: Buffer;
  /** 從繪製結果量到的品牌主色（measurePrimary，門檻為 brand.rules.maxDeltaE） */
  measured: MeasuredPrimary;
  /** 疊上文字與商品之前的背景，品牌色系的量測（measureBackgroundPalette） */
  background: BackgroundPalette;
}

/*
 * paint.ts 以 DOM 的型別撰寫，瀏覽器與 composer 共用同一份繪圖程式。@napi-rs/canvas 的 context 與 Image 在執行期
 * 提供 paint.ts 用到的所有 API（drawImage、fillText、measureText、letterSpacing、filter、shadowBlur、roundRect、
 * globalCompositeOperation…），但型別宣告是它自己的一套（例如 drawImage 只接受它的 Image），TypeScript 不認得兩者相容。
 * 只在這兩個函式轉型；poster.test.ts 實際畫出全部模板，驗證繪製結果。
 */
const domContext = (ctx: SKRSContext2D) => ctx as unknown as CanvasRenderingContext2D;
const domImage = (image: Image) => image as unknown as CanvasImageSource;

async function decode(label: string, data: Buffer): Promise<Image> {
  try {
    return await loadImage(data);
  } catch (err) {
    throw new Error(`${label}無法解碼：${err instanceof Error ? err.message : String(err)}`);
  }
}

const MISSING = (label: string, field: string) => `缺少${label}（${field}，base64）`;

function fromBase64(label: string, field: string, image: { base64: string } | null | undefined): Promise<Image> {
  if (typeof image?.base64 !== 'string' || image.base64 === '') return Promise.reject(new Error(MISSING(label, field)));
  return decode(label, Buffer.from(image.base64, 'base64'));
}

/** SVG 的 data URL（svgDataUrl 產生的 `data:image/svg+xml;charset=utf-8,…`）轉成 Buffer，交給 loadImage */
const svgBuffer = (dataUrl: string) => Buffer.from(decodeURIComponent(dataUrl.slice(dataUrl.indexOf(',') + 1)), 'utf8');

/** 示範商品依 productImage 產生 SVG；上傳商品用 worker 傳來的圖檔與 blend */
async function loadProduct(
  product: Product | null, brand: Brand, upload: PosterImages['product'] | undefined,
): Promise<{ image: Image; blend: 'normal' | 'multiply' } | null> {
  if (!product) return null;
  if (product.photo.source === 'sample') {
    const { src, blend } = productImage(product, brand);
    return { image: await decode('商品圖', svgBuffer(src)), blend };
  }
  if (!upload) throw new Error(MISSING('商品圖', 'images.product'));
  if (upload.blend !== 'normal' && upload.blend !== 'multiply') {
    throw new Error(`images.product.blend 必須是 normal 或 multiply：${JSON.stringify(upload.blend)}`);
  }
  return { image: await fromBase64('商品圖', 'images.product', upload), blend: upload.blend };
}

async function loadAssets(
  { render, product, brand, images = { product: null, logo: null } }: RenderPosterInput,
): Promise<{ assets: PaintAssets; background: Image }> {
  const spec = render.spec;
  const bg = render.background;
  const [background, prod, logo] = await Promise.all([
    bg.kind === 'procedural'
      ? decode('背景圖', Buffer.from(backgroundSvg({
        width: spec.canvas.width, height: spec.canvas.height, palette: bg.palette, seed: bg.seed, style: bg.style,
        focus: boxMap(spec.layout).product,
      }), 'utf8'))
      : fromBase64('背景圖', 'images.background', images.background),
    loadProduct(product, brand, images.product),
    // 與前端相同：品牌有 Logo 圖檔才使用，否則畫向量標誌與字標
    brand.logo && images.logo ? fromBase64('Logo 圖檔', 'images.logo', images.logo) : null,
  ]);
  const assets: PaintAssets = {
    background: domImage(background),
    // 沒有固有尺寸的圖以前端相同的預設尺寸計算
    product: prod
      ? { image: domImage(prod.image), width: prod.image.naturalWidth || 500, height: prod.image.naturalHeight || 800, blend: prod.blend }
      : null,
    logo: logo ? { image: domImage(logo), width: logo.naturalWidth || 300, height: logo.naturalHeight || 100 } : null,
    fonts: fontStacks(brand),
  };
  return { assets, background };
}

/**
 * 量背景的品牌色系：把背景縮小到長邊 sampleSide 再量（與海報相同的拉伸方式畫滿畫布），範圍扣掉商品方框。
 * 色票用品牌設定檔的（brand.palette），不是 spec 的：偏色的 spec 畫出的背景也要判定為色系外。
 */
export function measureBackground(background: Image, spec: Pick<PromptSpec, 'canvas' | 'layout'>, brand: Brand): BackgroundPalette {
  const { width: W, height: H } = spec.canvas;
  const scale = Math.min(1, BACKGROUND_MEASURE.sampleSide / Math.max(W, H));
  const width = Math.max(1, Math.round(W * scale));
  const height = Math.max(1, Math.round(H * scale));
  const ctx = createCanvas(width, height).getContext('2d');
  ctx.drawImage(background, 0, 0, width, height);
  const { data } = ctx.getImageData(0, 0, width, height);
  const p = boxMap(spec.layout).product;
  return measureBackgroundPalette({ data, width, height }, [p.x, p.y, p.w, p.h], spec.canvas, brand.palette);
}

/**
 * 以模板原始尺寸繪製海報（spec 的文案、版面與配色），量出品牌主色與背景色系，輸出 PNG。
 * 字型要先以 registerPosterFonts 註冊；圖檔缺少或無法解碼時丟出中文錯誤。
 */
export async function renderPoster(input: RenderPosterInput): Promise<RenderedPoster> {
  const { render, brand } = input;
  const spec = render.spec;
  const scene = composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: spec.copy, brand });
  const { assets, background } = await loadAssets(input);

  const width = Math.round(scene.width);
  const height = Math.round(scene.height);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  paintScene(domContext(ctx), scene, assets);

  const pixels = ctx.getImageData(0, 0, width, height).data;
  const measured = measurePrimary(pixels, width, height, spec.layout, brand.palette.primary, brand.rules.maxDeltaE);
  return { png: await canvas.encode('png'), measured, background: measureBackground(background, spec, brand) };
}
