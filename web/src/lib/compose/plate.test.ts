import { describe, it, expect } from 'vitest';
import { TEMPLATE_IDS, type TemplateId } from '@/types/contract';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { cleanSpec } from '@/test/fixtures';
import { boxMap } from './layout';
import { containBottom } from './paint';
import { dilateMask, GENERATION_SIZES, generationSize, plateGeometry, toTemplate } from './plate';
import { CHANNEL_TEMPLATES, getTemplate } from './templates';

const SERUM = SAMPLE_PRODUCTS.find((p) => p.brandId === 'selune')!;
const COFFEE = SAMPLE_PRODUCTS.find((p) => p.brandId === 'misty-isle')!;

describe('generationSize', () => {
  it('has an SDXL size of about one megapixel in multiples of 64 for every template ratio', () => {
    for (const t of CHANNEL_TEMPLATES) {
      const { width, height } = generationSize(t.ratio);
      expect(width % 64).toBe(0);
      expect(height % 64).toBe(0);
      expect(width * height).toBeGreaterThan(0.95e6);
      expect(width * height).toBeLessThan(1.1e6);
      // 與模板比例相差 < 5%：放大後只裁掉一點
      expect(Math.abs(width / height / (t.width / t.height) - 1)).toBeLessThan(0.05);
    }
    expect(Object.keys(GENERATION_SIZES).sort()).toEqual(CHANNEL_TEMPLATES.map((t) => t.ratio).sort());
  });

  it('rejects a ratio without a size', () => {
    expect(() => generationSize('3:2')).toThrow('沒有 3:2 的生成尺寸');
  });
});

describe('plateGeometry', () => {
  // 商品圖的三種比例：直立的瓶子、正方形、橫的盒子
  const SHAPES = [{ width: 500, height: 800 }, { width: 600, height: 600 }, { width: 900, height: 500 }];

  it.each(TEMPLATE_IDS)('%s: the product rect maps back to the rect paint draws, within a pixel', (id: TemplateId) => {
    for (const [brand, product] of [[SELUNE, SERUM], [MISTY_ISLE, COFFEE]] as const) {
      const spec = cleanSpec(brand, product, id);
      for (const shape of SHAPES) {
        const g = plateGeometry(spec, shape);
        const painted = containBottom(boxMap(spec.layout).product, shape.width, shape.height);
        const back = toTemplate(g, g.productRect!);
        for (const k of ['x', 'y', 'w', 'h'] as const) expect(Math.abs(back[k] - painted[k])).toBeLessThanOrEqual(1);
        expect(g).toMatchObject(generationSize(getTemplate(id).ratio));
      }
    }
  });

  it('covers the template: the scaled generation is at least the template size and the crop is centred', () => {
    for (const id of TEMPLATE_IDS) {
      const spec = cleanSpec(SELUNE, SERUM, id);
      const g = plateGeometry(spec, SHAPES[0]);
      const { width: W, height: H } = spec.canvas;
      expect(g.width * g.scale).toBeGreaterThanOrEqual(W - 1e-9);
      expect(g.height * g.scale).toBeGreaterThanOrEqual(H - 1e-9);
      expect(g.crop.x).toBeCloseTo((g.width * g.scale - W) / 2, 9);
      expect(g.crop.y).toBeCloseTo((g.height * g.scale - H) / 2, 9);
      expect(Math.min(g.crop.x, g.crop.y)).toBeCloseTo(0, 9);
    }
  });

  it('uses the whole product box when the product size is unknown, and has no rect without a product', () => {
    const spec = cleanSpec();
    const g = plateGeometry(spec, 'box');
    const box = boxMap(spec.layout).product;
    const back = toTemplate(g, g.productRect!);
    for (const k of ['x', 'y', 'w', 'h'] as const) expect(back[k]).toBeCloseTo(box[k], 6);
    expect(plateGeometry(spec, null).productRect).toBeNull();
  });
});

describe('dilateMask', () => {
  const grid = (rows: string[]) => Uint8Array.from(rows.join('').split('').map((c) => (c === '#' ? 1 : 0)));
  const show = (m: Uint8Array, w: number) => Array.from({ length: m.length / w }, (_, y) =>
    Array.from(m.subarray(y * w, y * w + w), (v) => (v ? '#' : '.')).join(''));

  it('grows the kept area by r pixels in every direction (a square)', () => {
    const m = grid(['.......', '.......', '.......', '...#...', '.......', '.......', '.......']);
    expect(show(dilateMask(m, 7, 7, 2), 7)).toEqual(['.......', '.#####.', '.#####.', '.#####.', '.#####.', '.#####.', '.......']);
  });

  it('stops at the edges and leaves the input alone', () => {
    const m = grid(['#..', '...', '...']);
    expect(show(dilateMask(m, 3, 3, 1), 3)).toEqual(['##.', '##.', '...']);
    expect(show(m, 3)).toEqual(['#..', '...', '...']);
    expect(dilateMask(m, 3, 3, 0)).toEqual(m);
  });
});
