import { describe, it, expect } from 'vitest';
import type { BBox, LayoutBox } from '@/types/contract';
import { computeLayout } from '@/lib/compose/layout';
import { getTemplate } from '@/lib/compose/templates';
import { mulberry32 } from '@/lib/core/num';
import { deltaEHex, hexToRgb, mixHex, rgbToLab } from './color';
import { measurePrimary, PRIMARY_MEASURE } from './measure';

const ROSE = '#B76E79';
const PINK = '#E0458A';
const BLUE = '#1E88E5';
const LAVENDER = '#B8A5D6';

// 240×200 的合成海報。量測範圍：標題 400 格 + 售價 400 格 + 徽章未被商品蓋住的 200 格 = 1000 個 4×4 格。
const W = 240;
const H = 200;
const HEADLINE: BBox = [0, 0, 160, 40];
const PRICE: BBox = [0, 160, 160, 40];
const BADGE: BBox = [160, 0, 80, 80];
const PRODUCT: BBox = [160, 40, 80, 160];
/** 標題與售價之間、量測範圍外的區域 */
const MIDDLE: BBox = [0, 40, 160, 120];
const LAYOUT: LayoutBox[] = [
  { id: 'logo', bbox: [0, 44, 60, 16], z: 2 },
  { id: 'headline', bbox: HEADLINE, z: 2 },
  { id: 'subhead', bbox: [0, 64, 160, 16], z: 2 },
  { id: 'features', bbox: [0, 84, 160, 16], z: 2 },
  { id: 'product', bbox: PRODUCT, z: 1 },
  { id: 'badge', bbox: BADGE, z: 3 },
  { id: 'price', bbox: PRICE, z: 2 },
  { id: 'disclaimer', bbox: [0, 104, 160, 16], z: 2 },
];

class Picture {
  readonly data: Uint8ClampedArray;
  constructor(readonly width: number, readonly height: number, background = '#FFFFFF') {
    this.data = new Uint8ClampedArray(width * height * 4);
    this.fill([0, 0, width, height], background);
  }

  fill([x0, y0, w, h]: BBox, hex: string, keep: (x: number, y: number) => boolean = () => true): this {
    const rgba = [...hexToRgb(hex), 255];
    for (let y = y0; y < y0 + h; y++) {
      for (let x = x0; x < x0 + w; x++) {
        if (keep(x, y)) this.data.set(rgba, (y * this.width + x) * 4);
      }
    }
    return this;
  }

  /** 像文字一樣的橫條：每 period 像素畫 thickness 像素高 */
  stripes(box: BBox, hex: string, period = 8, thickness = 4): this {
    return this.fill(box, hex, (_, y) => (y - box[1]) % period < thickness);
  }

  /** 每個 RGB 分量加上 ±amp 的均勻雜訊（固定 seed） */
  noise(amp: number, seed = 1): this {
    const rng = mulberry32(seed);
    for (let i = 0; i < this.data.length; i += 4) {
      for (let j = 0; j < 3; j++) this.data[i + j] = this.data[i + j] + Math.round((rng() * 2 - 1) * amp);
    }
    return this;
  }
}

const poster = (background = '#FFFFFF') => new Picture(W, H, background);
const measure = (p: Picture, primary = ROSE, maxDeltaE?: number) =>
  measurePrimary(p.data, p.width, p.height, LAYOUT, primary, maxDeltaE);

describe('measurePrimary', () => {
  it('measures the brand primary drawn in the headline, price and badge', () => {
    // 每個區塊一半的格子是主色：標題 200 + 售價 200 + 徽章 100 = 500 / 1000
    const p = poster().stripes(HEADLINE, ROSE).stripes(PRICE, ROSE).stripes(BADGE, ROSE);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.5, deltaE: 0 });
  });

  it('tolerates noise and anti-aliased edges', () => {
    // 6 像素高的橫條不對齊 4×4 格，邊緣的格子是混色；再加上 ±12 的雜訊
    const p = poster('#F6EFE9').stripes(HEADLINE, ROSE, 10, 6).stripes(PRICE, ROSE, 10, 6).noise(12);
    const r = measure(p);
    expect(r.hex).not.toBeNull();
    expect(r.deltaE).toBeLessThan(1.5);
    expect(r.share).toBeGreaterThan(0.2);
    expect(r.deltaE).toBe(deltaEHex(r.hex!, ROSE));
  });

  it('ignores colours outside the headline, price and badge boxes', () => {
    const p = poster().stripes(HEADLINE, ROSE).fill(MIDDLE, BLUE).fill(PRODUCT, BLUE);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.2, deltaE: 0 });
  });

  it('needs at least 2% of the region before a colour counts', () => {
    expect(PRIMARY_MEASURE.minShare).toBe(0.02);
    expect(measure(poster().fill([0, 0, 4 * 19, 4], ROSE))).toEqual({ hex: null, share: 0, deltaE: null });
    expect(measure(poster().fill([0, 0, 4 * 20, 4], ROSE))).toEqual({ hex: '#b76e79', share: 0.02, deltaE: 0 });
  });

  it('returns null when nothing in the region is chromatic', () => {
    const p = poster().stripes(HEADLINE, '#000000').stripes(PRICE, '#808080').fill(BADGE, '#F0F0F0').fill(MIDDLE, BLUE);
    expect(measure(p)).toEqual({ hex: null, share: 0, deltaE: null });
    expect(measure(poster())).toEqual({ hex: null, share: 0, deltaE: null });
  });

  it('measures a neutral primary without a chroma floor', () => {
    const p = poster().stripes(HEADLINE, '#222222').stripes(PRICE, '#222222').stripes(BADGE, '#222222');
    expect(measure(p, '#222222')).toEqual({ hex: '#222222', share: 0.5, deltaE: 0 });
  });

  it('measures a pale pastel primary on a cream background', () => {
    const p = poster('#FFF8F0').stripes(HEADLINE, '#F2C4CE').stripes(PRICE, '#F2C4CE');
    expect(measure(p, '#F2C4CE')).toEqual({ hex: '#f2c4ce', share: 0.4, deltaE: 0 });
  });

  it('keeps the nearest colour when it passes, even next to a more vivid one', () => {
    const p = poster().stripes(HEADLINE, ROSE).fill(BADGE, PINK);
    expect(measure(p)).toEqual({ hex: '#b76e79', share: 0.2, deltaE: 0 });
  });

  it('shows the most vivid candidate when even the nearest one is off-brand', () => {
    // 偏色海報：淺藍底（離品牌淡紫較近）上的鮮藍字。判定一樣不通過，但說明要顯示實際用錯的鮮藍
    const LIGHT_BLUE = '#CFE7FA';
    expect(deltaEHex(LIGHT_BLUE, LAVENDER)).toBeLessThan(deltaEHex(BLUE, LAVENDER));
    expect(deltaEHex(LIGHT_BLUE, LAVENDER)).toBeGreaterThan(5);
    const p = poster().fill(HEADLINE, LIGHT_BLUE).fill(PRICE, LIGHT_BLUE).fill(BADGE, LIGHT_BLUE).stripes(HEADLINE, BLUE);

    expect(measure(p, LAVENDER)).toEqual({ hex: '#1e88e5', share: 0.2, deltaE: deltaEHex('#1e88e5', LAVENDER) });
    // 門檻放寬到最近的顏色也算通過時，回報最近的顏色
    expect(measure(p, LAVENDER, 30)).toEqual({ hex: '#cfe7fa', share: 0.8, deltaE: deltaEHex('#cfe7fa', LAVENDER) });
  });

  it('excludes the product box even where it overlaps a role box', () => {
    // 商品（品牌色）蓋在徽章上；排除後只剩標題的偏色，分母也不含商品的格子
    const p = poster().fill(PRODUCT, ROSE).stripes(HEADLINE, PINK);
    expect(measure(p)).toEqual({ hex: '#e0458a', share: 0.2, deltaE: deltaEHex('#e0458a', ROSE) });
  });

  it('samples whole 4×4 blocks whose centre lies in the region', () => {
    // 10×8 的畫布、標題框 x 0–6：只有 x 0–3 那一欄格子的中心（x = 2）在框內；x 8–9 湊不滿一格
    const layout: LayoutBox[] = [
      { id: 'headline', bbox: [0, 0, 6, 8], z: 2 },
      ...(['price', 'badge', 'product'] as const).map((id) => ({ id, bbox: [0, 0, 0, 0] as BBox, z: 2 })),
    ];
    const tiny = (left: string, right: string) => new Picture(10, 8).fill([0, 0, 4, 8], left).fill([4, 0, 6, 8], right);
    const run = (p: Picture) => measurePrimary(p.data, 10, 8, layout, ROSE);
    expect(run(tiny(ROSE, BLUE))).toEqual({ hex: '#b76e79', share: 1, deltaE: 0 });
    expect(run(tiny(BLUE, ROSE))).toMatchObject({ hex: '#1e88e5', share: 1 });
  });

  it('averages the 16 pixels of each block', () => {
    const half = poster().fill(HEADLINE, ROSE, (x, y) => (x + y) % 2 === 0).fill(PRICE, ROSE, (x, y) => (x + y) % 2 === 0);
    const mix = mixHex(ROSE, '#FFFFFF', 0.5);
    expect(measure(half, mix)).toEqual({ hex: mix, share: 0.8, deltaE: 0 });
  });

  it('merges neighbouring Lab bins into one candidate', () => {
    const bin = (hex: string) => {
      const { L, a, b } = rgbToLab(hexToRgb(hex));
      return [L, a, b].map((v) => Math.floor(v / PRIMARY_MEASURE.bin));
    };
    const [l0, a0, b0] = bin(ROSE);
    const shade = Array.from({ length: 40 }, (_, i) => mixHex(ROSE, '#000000', (i + 1) / 400)).find((hex) => {
      const [l, a, b] = bin(hex);
      return (l !== l0 || a !== a0 || b !== b0) && Math.max(Math.abs(l - l0), Math.abs(a - a0), Math.abs(b - b0)) === 1;
    });
    expect(shade).toBeDefined();
    // 主色 200 格、相鄰格的深一點的主色 120 格：合併成一個佔 32% 的候選
    const p = poster().stripes(HEADLINE, ROSE).stripes(PRICE, shade!, 40, 12);
    const r = measure(p);
    expect(r.share).toBeCloseTo(0.32, 10);
    expect(r.deltaE).toBeLessThan(1);
  });

  it('works on a real template layout and leaves the pixels untouched', () => {
    const t = getTemplate('ig-post');
    const layout = computeLayout(t);
    const p = new Picture(t.width, t.height, '#F6EFE9');
    for (const box of layout) if (box.id === 'headline' || box.id === 'price' || box.id === 'badge') p.stripes(box.bbox, ROSE, 12, 8);
    p.fill(layout.find((b) => b.id === 'product')!.bbox, BLUE);
    const before = p.data.slice();
    const r = measurePrimary(p.data, t.width, t.height, layout, ROSE);
    expect(r).toMatchObject({ hex: '#b76e79', deltaE: 0 });
    expect(r.share).toBeGreaterThan(0.5);
    expect(Buffer.from(p.data).equals(Buffer.from(before))).toBe(true);
    expect(measurePrimary(p.data, t.width, t.height, layout, ROSE)).toEqual(r);
  });
});
