import { describe, it, expect } from 'vitest';
import type { BBox, Palette } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { deltaEHex, hexToRgb, mixHex } from './color';
import { BACKGROUND_MEASURE, bgPaletteCheck, measureBackgroundPalette, type BackgroundPixels } from './background';

const W = 200;
const H = 100;
const CANVAS = { width: W, height: H };
/** 右下角一小塊商品方框 */
const PRODUCT: BBox = [150, 60, 40, 30];
const PALETTE: Palette = SELUNE.palette;

/** 依座標給顏色的不透明像素 */
function pixels(width: number, height: number, color: (x: number, y: number) => string): BackgroundPixels {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const [r, g, b] = hexToRgb(color(x, y));
      data.set([r, g, b, 255], (y * width + x) * 4);
    }
  }
  return { data, width, height };
}
const solid = (hex: string) => pixels(W, H, () => hex);
const measure = (p: BackgroundPixels, product: BBox = PRODUCT) => measureBackgroundPalette(p, product, CANVAS, PALETTE);

describe('measureBackgroundPalette', () => {
  it('counts nothing as off-palette on the brand colours', () => {
    for (const hex of [PALETTE.primary, PALETTE.secondary, PALETTE.accent, PALETTE.ink]) {
      expect(measure(solid(hex))).toMatchObject({ offShare: 0, offHex: null });
    }
  });

  it('treats greys, white and black as neutral', () => {
    for (const hex of ['#808080', '#FFFFFF', '#000000', '#F2F0EE']) expect(measure(solid(hex)).offShare).toBe(0);
  });

  it('keeps a gradient between the primary and the secondary on the palette', () => {
    const gradient = pixels(W, H, (x) => mixHex(PALETTE.primary, PALETTE.secondary, x / (W - 1)));
    expect(measure(gradient).offShare).toBe(0);
  });

  it('measures the share of a neon half and names its colour', () => {
    const half = measure(pixels(W, H, (x) => (x < W / 2 ? '#39FF14' : PALETTE.secondary)), [0, 0, 0, 0]);
    expect(half.offShare).toBeCloseTo(0.5, 1);
    expect(deltaEHex(half.offHex!, '#39FF14')).toBeLessThan(5);
  });

  it('counts the brand hue as off-palette when it is far more saturated than the brand colour', () => {
    // SÉLUNE 主色 #B76E79 的色相，但彩度高得多（品牌指南禁止的高飽和桃紅）
    expect(measure(solid('#E0458A')).offShare).toBe(1);
    // 色相相同、彩度只高一點的仍在色系內
    expect(measure(solid('#C2606F')).offShare).toBe(0);
  });

  // Plan 7 規格 §12 的實測：ComfyUI 生成的背景
  it('uses a muted brand colour as a hue reference too (misty-isle: dark teal, C* 11.8)', () => {
    const misty: Palette = { primary: '#2F4A44', secondary: '#EEF0EC', accent: '#C8A27A', ink: '#1F2624' };
    const of = (hex: string) => measureBackgroundPalette(solid(hex), PRODUCT, CANVAS, misty).offShare;
    expect(of('#10483A')).toBe(0); // 品牌的深青綠
    expect(of('#899577')).toBe(0); // 很淡的灰綠：彩度低，算中性色
    expect(of('#39FF14')).toBe(1);
  });

  it('flags a clearly green background on a rose and gold brand', () => {
    expect(measure(solid('#5C6D46')).offShare).toBe(1);
  });

  it('flags a saturated blue on a lavender brand although the hues are close', () => {
    const kayla: Palette = { primary: '#B8A5D6', secondary: '#F9F4E8', accent: '#C9A96E', ink: '#3A3335' };
    expect(measureBackgroundPalette(solid('#1456AC'), PRODUCT, CANVAS, kayla).offShare).toBe(1);
    expect(measureBackgroundPalette(solid('#B8A5D6'), PRODUCT, CANVAS, kayla).offShare).toBe(0);
  });

  it('leaves the product box (with a margin) out of the measurement', () => {
    const [px, py, pw, ph] = PRODUCT;
    const neonProduct = pixels(W, H, (x, y) => (x >= px && x < px + pw && y >= py && y < py + ph ? '#39FF14' : PALETTE.primary));
    expect(measure(neonProduct).offShare).toBe(0);
    expect(measure(neonProduct, [0, 0, 0, 0]).offShare).toBeGreaterThan(0);
  });

  it('scales the product box from the canvas to a smaller sample', () => {
    // 樣本只有畫布的一半大：商品框也縮成一半
    const [px, py, pw, ph] = PRODUCT;
    const small = pixels(W / 2, H / 2, (x, y) =>
      (x >= px / 2 && x < (px + pw) / 2 && y >= py / 2 && y < (py + ph) / 2 ? '#39FF14' : PALETTE.secondary));
    expect(measureBackgroundPalette(small, PRODUCT, CANVAS, PALETTE)).toMatchObject({ offShare: 0, sampled: expect.any(Number) });
  });

  it('samples at most about SAMPLE_SIDE × SAMPLE_SIDE pixels of a large background', () => {
    const big = pixels(1600, 1600, () => PALETTE.secondary);
    const { sampled } = measureBackgroundPalette(big, [0, 0, 0, 0], { width: 1600, height: 1600 }, PALETTE);
    expect(sampled).toBeLessThanOrEqual(BACKGROUND_MEASURE.sampleSide ** 2);
    expect(sampled).toBeGreaterThan((BACKGROUND_MEASURE.sampleSide / 2) ** 2);
  });

  it('reports nothing sampled when the product covers the whole background', () => {
    expect(measure(solid('#39FF14'), [0, 0, W, H])).toEqual({ offShare: 0, offHex: null, sampled: 0 });
  });

  it('feeds bgPaletteCheck: a mostly neon background fails and shows the colour', () => {
    const check = bgPaletteCheck(measure(solid('#39FF14')));
    expect(check.status).toBe('fail');
    expect(check.value).toMatch(/^色系外 \d+%（主要為 #[0-9A-F]{6}）$/);
  });
});
