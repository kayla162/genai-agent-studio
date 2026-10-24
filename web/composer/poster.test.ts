import type { AddressInfo } from 'node:net';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { Brand, Product, PromptSpec, Render, ReviewCheck, TemplateId } from '@/types/contract';
import { TEMPLATE_IDS } from '@/types/contract';
import { seedOf } from '@/lib/agent/prompt';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { boxMap } from '@/lib/compose/layout';
import { fitLogoImage } from '@/lib/compose/scene';
import { getTemplate } from '@/lib/compose/templates';
import { backgroundSvg, svgDataUrl } from '@/lib/compose/art';
import { bgPaletteCheck, type BackgroundPalette } from '@/lib/review/background';
import { deltaEHex } from '@/lib/review/color';
import { runRuleChecks } from '@/lib/review/rules';
import { cleanSpec } from '@/test/fixtures';
import { createComposerServer } from './app';
import { FONTS_HINT, missingPosterFonts, registerPosterFonts, resolveFontsDir } from './fonts';
import { measureBackground, renderPoster, type PosterImages, type RenderedPoster } from './poster';

const FONTS_DIR = resolveFontsDir();
const MISSING = missingPosterFonts(FONTS_DIR);
if (MISSING.length) console.warn(`略過需要字型的海報測試：找不到 ${MISSING.join('、')}。${FONTS_HINT}`);

/** 第三個品牌：仿 brands/my-brand-01.yaml（淡紫主色、背景風格退回 plain），只用於測試 */
const KAYLA: Brand = {
  id: 'my-brand-01',
  name: 'Kayla 精緻少女',
  category: '美妝保養',
  ciVersion: 'v1.0',
  palette: { primary: '#B8A5D6', secondary: '#F9F4E8', accent: '#C9A96E', ink: '#3A3335' },
  fonts: { headline: 'Noto Serif TC', body: 'Noto Sans TC' },
  visualStyle: 'warm minimal product photography, natural linen texture, soft morning light',
  defaultTone: 'science',
  rules: { maxDeltaE: 5, minWhitespace: 0.3, productRatio: [0.3, 0.5] },
  bannedWords: ['根治', '治療', '保證有效'],
  replacements: { 根治: '', 治療: '', 保證有效: '' },
  claimWords: ['修護', '改善'],
  disclaimerPhrase: '效果因個人膚況而異',
  guidelineChunks: [],
  caseStudies: [],
  copyPresets: {
    gentle: { headline: ['溫柔呵護', '每一天'], subhead: '天然成分・溫和配方' },
    science: { headline: ['科學配方', '看得見的改變'], subhead: '專利成分・臨床測試' },
    playful: { headline: ['今天也要', '閃閃發光！'], subhead: '限時優惠，手刀搶購' },
    minimal: { headline: ['簡單', '就是美'], subhead: '純粹成分・無多餘添加' },
  },
  logo: null,
};
const KAYLA_SERUM: Product = {
  id: 'prod_my_brand_serum', brandId: 'my-brand-01', name: '薰衣草舒緩精華 30ml',
  features: ['溫和配方', '天然成分', '保濕鎖水', '敏感肌適用'],
  price: { sale: 980, original: 1280 }, photo: { source: 'sample', art: 'serum' },
  cutout: null, createdAt: '2026-10-01T09:00:00.000Z',
};
const SERUM = SAMPLE_PRODUCTS.find((p) => p.brandId === 'selune')!;
const CASES = [
  { brand: SELUNE, product: SERUM },
  { brand: MISTY_ISLE, product: SAMPLE_PRODUCTS.find((p) => p.brandId === 'misty-isle')! },
  { brand: KAYLA, product: KAYLA_SERUM },
];

const NO_IMAGES: PosterImages = { product: null, logo: null };
/** 一張海報約 0.1–0.6 秒（PNG 編碼佔大半），測試同時執行時會更慢 */
const SLOW = 20_000;

/** 與 mock 劇本相同的候選：程式產生的背景，配色取自 spec */
const renderOf = (spec: PromptSpec, brand: Brand): Render => ({
  id: `${spec.jobId}_r${spec.round}_${spec.templateId}_v0`, jobId: spec.jobId, round: spec.round, templateId: spec.templateId,
  variant: 0, background: { kind: 'procedural', seed: seedOf(spec), palette: spec.palette, style: brand.id },
  spec, score: null, passed: null, checks: [],
});

/** PNG 的尺寸（IHDR），順便確認檔頭 */
function pngSize(png: Buffer): { width: number; height: number } {
  expect([...png.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

/** 解碼 PNG，回傳讀取某個像素 RGB 的函式 */
async function pixelsOf(png: Buffer): Promise<(x: number, y: number) => number[]> {
  const img = await loadImage(png);
  const ctx = createCanvas(img.width, img.height).getContext('2d');
  ctx.drawImage(img, 0, 0);
  const { data, width } = ctx.getImageData(0, 0, img.width, img.height);
  return (x, y) => {
    const i = (Math.floor(y) * width + Math.floor(x)) * 4;
    return [data[i], data[i + 1], data[i + 2]];
  };
}

/** 單色 PNG 的 base64 */
async function solidPng(width: number, height: number, color: string): Promise<string> {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, width, height);
  return (await canvas.encode('png')).toString('base64');
}

const colorDelta = (brand: Brand, spec: PromptSpec, { measured }: RenderedPoster): ReviewCheck =>
  runRuleChecks({ brand, spec, measuredPrimary: measured.hex }).find((c) => c.id === 'color_delta')!;

describe('renderPoster input errors', () => {
  const spec = cleanSpec();
  const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.png' } };

  it('requires the uploaded product image and a valid blend', async () => {
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images: NO_IMAGES }))
      .rejects.toThrow('缺少商品圖（images.product，base64）');
    const images = { product: { base64: await solidPng(4, 4, '#ffffff'), blend: 'screen' }, logo: null } as unknown as PosterImages;
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images }))
      .rejects.toThrow('images.product.blend 必須是 normal 或 multiply："screen"');
  });

  it('names the image that cannot be decoded', async () => {
    const images: PosterImages = { product: { base64: Buffer.from('不是圖片').toString('base64'), blend: 'normal' }, logo: null };
    await expect(renderPoster({ render: renderOf(spec, SELUNE), product: upload, brand: SELUNE, images }))
      .rejects.toThrow(/^商品圖無法解碼：/);
  });

  it('requires the background image of a url background', async () => {
    const render: Render = { ...renderOf(spec, SELUNE), background: { kind: 'url', url: '/files/bg.png', includesProduct: false } };
    await expect(renderPoster({ render, product: SERUM, brand: SELUNE, images: NO_IMAGES }))
      .rejects.toThrow('缺少背景圖（images.background，base64）');
  });
});

// Plan 7 規格 §2：程式產生的背景（3 個品牌 × 5 個模板 × 2 個 seed）在背景色系檢查全部通過
describe('background palette of the procedural backgrounds', () => {
  describe.each(CASES)('$brand.id', ({ brand, product }) => {
    it.each(TEMPLATE_IDS)('%s passes bg_palette for two seeds', async (id: TemplateId) => {
      const spec = cleanSpec(brand, product, id);
      for (const seed of [seedOf(spec), seedOf(spec) + 1]) {
        const svg = backgroundSvg({
          width: spec.canvas.width, height: spec.canvas.height, palette: spec.palette, seed, style: brand.id,
          focus: boxMap(spec.layout).product,
        });
        const image = await loadImage(Buffer.from(decodeURIComponent(svgDataUrl(svg).split(',')[1]), 'utf8'));
        const measured = measureBackground(image, spec, brand);
        expect({ seed, ...bgPaletteCheck(measured) }).toMatchObject({ seed, status: 'pass' });
      }
    }, SLOW);
  });
});

describe.skipIf(MISSING.length > 0)(`renderPoster with the poster fonts（沒有字型時略過：${FONTS_HINT}）`, () => {
  beforeAll(() => {
    registerPosterFonts(FONTS_DIR);
  });

  // 設計規格 §7：3 個品牌 × 5 個模板，正確配色全部通過、偏色全部不通過
  describe.each(CASES)('$brand.id', ({ brand, product }) => {
    it.each(TEMPLATE_IDS)('%s: native size, the clean spec passes color_delta, the flawed one fails with its wrong colour', async (id: TemplateId) => {
      const clean = cleanSpec(brand, product, id);
      const flawed = applyFlaws(clean, FLAWS, brand);
      const ok = await renderPoster({ render: renderOf(clean, brand), product, brand, images: NO_IMAGES });
      const bad = await renderPoster({ render: renderOf(flawed, brand), product, brand, images: NO_IMAGES });
      const { width, height } = getTemplate(id);
      expect(pngSize(ok.png)).toEqual({ width, height });
      expect(pngSize(bad.png)).toEqual({ width, height });

      expect(ok.measured.hex).not.toBeNull();
      expect(ok.measured.deltaE).toBeLessThanOrEqual(brand.rules.maxDeltaE);
      expect(colorDelta(brand, clean, ok).status).toBe('pass');

      expect(bad.measured.deltaE).toBeGreaterThan(brand.rules.maxDeltaE);
      expect(colorDelta(brand, flawed, bad).status).toBe('fail');
      // 說明文字顯示實際用錯的顏色：量到的是偏色 spec 的主色
      expect(deltaEHex(bad.measured.hex!, flawed.palette.primary)).toBeLessThanOrEqual(brand.rules.maxDeltaE);
    }, SLOW);
  });

  it('draws the uploaded product, the logo file and a url background from base64', async () => {
    const brand: Brand = { ...SELUNE, logo: { url: '/files/brands/selune/logo.svg' } };
    const upload: Product = {
      ...SERUM, photo: { source: 'upload', url: '/files/products/serum.jpg' },
      cutout: { model: 'birefnet', status: 'done', url: '/files/products/serum.png', error: null },
    };
    const spec = cleanSpec(SELUNE, SERUM, 'ig-post');
    const render: Render = { ...renderOf(spec, brand), background: { kind: 'url', url: '/files/bg.png', includesProduct: false } };
    const logoSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"><rect width="300" height="100" fill="#ff0000"/></svg>';
    const images = async (blend: 'normal' | 'multiply'): Promise<PosterImages> => ({
      product: { base64: await solidPng(100, 100, '#00ff00'), blend },
      logo: { base64: Buffer.from(logoSvg).toString('base64') },
      background: { base64: await solidPng(64, 64, '#0000ff') },
    });

    const B = boxMap(spec.layout);
    // 100×100 的商品圖等比縮放進商品框、底部對齊；量中心點
    const side = Math.min(B.product.w, B.product.h);
    const productCentre = [B.product.x + B.product.w / 2, B.product.y + B.product.h - side / 2] as const;
    const logo = fitLogoImage(B.logo, 300, 100);

    const normal = await renderPoster({ render, product: upload, brand, images: await images('normal') });
    // 純藍的背景不在 SÉLUNE 的色系（玫瑰、米白、金）內：量的是疊上文字與商品之前的背景
    expect(normal.background.offShare).toBe(1);
    expect(bgPaletteCheck(normal.background)).toMatchObject({ status: 'fail', value: '色系外 100%（主要為 #0000FF）' });
    const px = await pixelsOf(normal.png);
    expect(px(2, 2)).toEqual([0, 0, 255]);
    expect(px(...productCentre)).toEqual([0, 255, 0]);
    expect(px(logo.x + logo.w / 2, logo.y + logo.h / 2)).toEqual([255, 0, 0]);
    expect(colorDelta(brand, spec, normal).status).toBe('pass');

    // 色彩增值：綠 × 藍 = 黑
    const multiply = await renderPoster({ render, product: upload, brand, images: await images('multiply') });
    expect((await pixelsOf(multiply.png))(...productCentre)).toEqual([0, 0, 0]);
  }, SLOW);

  it('draws the vector logo when the brand has a logo file but none was sent', async () => {
    const brand: Brand = { ...SELUNE, logo: { url: '/files/brands/selune/logo.svg' } };
    const spec = cleanSpec();
    const out = await renderPoster({ render: renderOf(spec, brand), product: SERUM, brand, images: NO_IMAGES });
    expect(pngSize(out.png)).toEqual({ width: spec.canvas.width, height: spec.canvas.height });
  });
});

describe.skipIf(MISSING.length > 0)(`POST /render（沒有字型時略過：${FONTS_HINT}）`, () => {
  const server = createComposerServer({ fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  let base = '';
  beforeAll(async () => {
    registerPosterFonts(FONTS_DIR);
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });
  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  const post = (path: string, body: unknown) =>
    fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  it('returns the PNG with the measured primary and its share, which /review accepts', async () => {
    const spec = cleanSpec(SELUNE, SERUM, 'story');
    const input = { render: renderOf(spec, SELUNE), product: SERUM, brand: SELUNE, images: NO_IMAGES };
    const res = await post('/render', input);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('image/png');
    const png = Buffer.from(await res.arrayBuffer());
    expect(pngSize(png)).toEqual({ width: getTemplate('story').width, height: getTemplate('story').height });

    const { measured, background } = await renderPoster(input);
    const primary = res.headers.get('x-measured-primary');
    expect(primary).toBe(measured.hex);
    expect(Number(res.headers.get('x-primary-share'))).toBeCloseTo(measured.share, 4);
    const sent = JSON.parse(res.headers.get('x-background-palette')!) as BackgroundPalette;
    expect(sent).toEqual({ ...background, offShare: Number(background.offShare.toFixed(4)) });

    const review = await post('/review', { spec, brand: SELUNE, measuredPrimary: primary, background: sent });
    const body = (await review.json()) as { checks: ReviewCheck[]; score: number; passed: boolean };
    expect(body.checks.find((c) => c.id === 'color_delta')!.status).toBe('pass');
    expect(body.checks.find((c) => c.id === 'bg_palette')).toMatchObject({ status: 'pass', value: expect.stringMatching(/^色系外 \d+%$/) });
    expect(body).toMatchObject({ score: 100, passed: true });
  }, SLOW);

  it('sends an empty X-Measured-Primary when the poster has no colour to measure', async () => {
    // 全部改成灰階：範圍內沒有彩色，量不到主色
    const spec: PromptSpec = { ...cleanSpec(), palette: { primary: '#777777', secondary: '#EEEEEE', accent: '#999999', ink: '#222222' } };
    const res = await post('/render', { render: renderOf(spec, SELUNE), product: null, brand: SELUNE, images: NO_IMAGES });
    expect(res.status).toBe(200);
    expect(res.headers.get('x-measured-primary')).toBe('');
    expect(res.headers.get('x-primary-share')).toBe('0');
  });

  it('answers 400 with a Chinese message when an image is missing', async () => {
    const upload: Product = { ...SERUM, photo: { source: 'upload', url: '/files/products/serum.png' } };
    const res = await post('/render', { render: renderOf(cleanSpec(), SELUNE), product: upload, brand: SELUNE, images: NO_IMAGES });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: { code: 'invalid', message: '缺少商品圖（images.product，base64）' } });
  });
});
