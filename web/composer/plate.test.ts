import { createCanvas, loadImage } from '@napi-rs/canvas';
import { describe, expect, it } from 'vitest';
import type { Product } from '@/types/contract';
import { SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { generationSize } from '@/lib/compose/plate';
import { cleanSpec } from '@/test/fixtures';
import { handle } from './handlers';
import { PLATE_GREY, renderPlate, type PlateResult } from './plate';

const SERUM = SAMPLE_PRODUCTS.find((p) => p.brandId === 'selune')!;
const SPEC = cleanSpec(SELUNE, SERUM, 'ig-post');
const NO_IMAGES = { product: null, logo: null };

/** 解碼 base64 PNG，回傳尺寸與讀取像素 RGB 的函式 */
async function decoded(base64: string) {
  const img = await loadImage(Buffer.from(base64, 'base64'));
  const ctx = createCanvas(img.width, img.height).getContext('2d');
  ctx.drawImage(img, 0, 0);
  const { data } = ctx.getImageData(0, 0, img.width, img.height);
  const at = (x: number, y: number) => {
    const i = (Math.floor(y) * img.width + Math.floor(x)) * 4;
    return [data[i], data[i + 1], data[i + 2]];
  };
  let black = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] === 0) black++;
  return { width: img.width, height: img.height, at, black };
}

async function solidPng(width: number, height: number, color: string): Promise<string> {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, width, height);
  return (await canvas.encode('png')).toString('base64');
}

const centre = (r: PlateResult['productRect']) => [r!.x + r!.w / 2, r!.y + r!.h / 2] as const;

describe('renderPlate', () => {
  it('draws the sample product on grey at the generation size and masks everything but the product', async () => {
    const out = await renderPlate({ spec: SPEC, product: SERUM, brand: SELUNE, images: NO_IMAGES });
    const size = generationSize(SPEC.canvas.ratio);
    expect(out).toMatchObject({ ...size, warning: null });
    const plate = await decoded(out.plate);
    const mask = await decoded(out.mask);
    expect([plate.width, plate.height, mask.width, mask.height]).toEqual([size.width, size.height, size.width, size.height]);
    expect(plate.at(1, 1)).toEqual(PLATE_GREY);
    expect(mask.at(1, 1)).toEqual([255, 255, 255]);
    expect(mask.at(...centre(out.productRect))).toEqual([0, 0, 0]);
    expect(plate.at(...centre(out.productRect))).not.toEqual(PLATE_GREY);
  });

  it('grows the kept area around the product by PLATE_MASK_GROW pixels', async () => {
    const input = { spec: SPEC, product: SERUM, brand: SELUNE, images: NO_IMAGES };
    const tight = await decoded((await renderPlate(input, 0)).mask);
    const grown = await decoded((await renderPlate(input)).mask);
    expect(grown.black).toBeGreaterThan(tight.black);
  });

  it('keeps the whole product box of a photo that is not cut out yet, and warns', async () => {
    const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.jpg' }, cutout: null };
    const images = { product: { base64: await solidPng(300, 400, '#00ff00'), blend: 'multiply' as const }, logo: null };
    const out = await renderPlate({ spec: SPEC, product: upload, brand: SELUNE, images });
    expect(out.warning).toBe('商品尚未去背，背景依外框生成');
    const mask = await decoded(out.mask);
    const r = out.productRect!;
    // 照片的矩形內全部保留（黑），連照片的四個角落都是
    expect(mask.at(r.x + 1, r.y + 1)).toEqual([0, 0, 0]);
    expect(mask.at(r.x + r.w - 2, r.y + r.h - 2)).toEqual([0, 0, 0]);
    expect((await decoded(out.plate)).at(...centre(r))).toEqual([0, 255, 0]);
  });

  it('masks everything when the product was deleted', async () => {
    const out = await renderPlate({ spec: SPEC, product: null, brand: SELUNE, images: NO_IMAGES });
    expect(out.productRect).toBeNull();
    expect((await decoded(out.mask)).black).toBe(0);
  });

  it('needs the uploaded product image, like /render', async () => {
    const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.png' } };
    await expect(renderPlate({ spec: SPEC, product: upload, brand: SELUNE, images: NO_IMAGES }))
      .rejects.toThrow('缺少商品圖（images.product，base64）');
  });

  it('is served at POST /plate', async () => {
    const out = (await handle('/plate', { spec: SPEC, product: SERUM, brand: SELUNE, images: NO_IMAGES })) as PlateResult;
    expect(out).toEqual(await renderPlate({ spec: SPEC, product: SERUM, brand: SELUNE, images: NO_IMAGES }));
  });
});
