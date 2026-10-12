import { describe, it, expect } from 'vitest';
import type { Copy, LayoutElementId, PromptSpec } from '@/types/contract';
import { CHANNEL_TEMPLATES } from './templates';
import { boxMap } from './layout';
import {
  composePoster, fitLogoImage, formatPrice, logoFor, textBounds, type BadgeOp, type LogoOp, type PillOp, type SceneInput,
  type TextOp,
} from './scene';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE } from '@/lib/api/mock/data';

const sceneInput = (spec: PromptSpec, copy: Partial<Copy> = {}): SceneInput => ({
  canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: { ...spec.copy, ...copy }, brand: SELUNE,
});
const texts = (ops: ReturnType<typeof composePoster>['ops']) => ops.filter((o): o is TextOp => o.kind === 'text');
const inside = (r: { x: number; y: number; w: number; h: number }, box: { x: number; y: number; w: number; h: number }) =>
  r.x >= box.x - 0.5 && r.y >= box.y - 0.5 && r.x + r.w <= box.x + box.w + 0.5 && r.y + r.h <= box.y + box.h + 0.5;

describe.each(CHANNEL_TEMPLATES)('composePoster($id)', (t) => {
  const spec = cleanSpec(SELUNE, undefined, t.id);
  const B = boxMap(spec.layout);
  const scene = composePoster(sceneInput(spec));

  it('keeps every text inside its layout box', () => {
    for (const op of texts(scene.ops)) expect(inside(textBounds(op), B[op.el]), `${op.el}: ${op.text}`).toBe(true);
    const logo = scene.ops.find((o): o is LogoOp => o.kind === 'logo')!;
    expect(inside(textBounds(logo.wordmark!), B.logo)).toBe(true);
  });

  it('keeps badge texts inside the badge circle', () => {
    const badge = scene.ops.find((o): o is BadgeOp => o.kind === 'badge')!;
    for (const op of badge.texts) {
      const b = textBounds(op);
      expect(Math.abs(b.x + b.w / 2 - badge.cx)).toBeLessThan(0.01);
      expect(b.w / 2).toBeLessThanOrEqual(badge.r * 0.75);
      expect(Math.abs(op.y - badge.cy) + op.size / 2).toBeLessThanOrEqual(badge.r * 0.75);
    }
  });

  it('keeps feature pills inside the features box', () => {
    const pills = scene.ops.filter((o): o is PillOp => o.kind === 'pill' && o.el === 'features');
    expect(pills.length).toBeGreaterThan(0);
    for (const p of pills) expect(inside(p.rect, B.features)).toBe(true);
  });

  it('draws the background first, the product second and the badge last', () => {
    expect(scene.ops[0].kind).toBe('background');
    expect(scene.ops[1].kind).toBe('product');
    expect(scene.ops.at(-1)!.kind).toBe('badge');
    expect(scene).toMatchObject({ width: t.width, height: t.height });
  });
});

describe('composePoster with edited copy', () => {
  const spec = cleanSpec();
  const B = boxMap(spec.layout);

  it('shrinks a long headline so it still fits', () => {
    const base = texts(composePoster(sceneInput(spec)).ops).find((o) => o.el === 'headline')!;
    const long = texts(composePoster(sceneInput(spec, { headline: ['這是一個非常非常非常長的標題', '第二行'] })).ops)
      .filter((o) => o.el === 'headline');
    expect(long[0].size).toBeLessThan(base.size);
    for (const op of long) expect(inside(textBounds(op), B.headline)).toBe(true);
  });

  it('shows the edited price with thousands separators', () => {
    const ops = texts(composePoster(sceneInput(spec, { price: { ...spec.copy.price, sale: 12800 } })).ops);
    expect(ops.map((o) => o.text)).toContain('12,800');
    expect(ops.map((o) => o.text)).toContain('NT$');
  });

  it('skips empty optional fields', () => {
    const scene = composePoster(sceneInput(spec, {
      subhead: '', features: [], disclaimer: '', badge: { top: '', main: '', sub: '' },
      price: { label: '', sale: 100, original: 100 }, headline: ['只有一行', ''],
    }));
    const els = new Set<LayoutElementId>(texts(scene.ops).map((o) => o.el));
    expect(els.has('subhead') || els.has('features') || els.has('disclaimer')).toBe(false);
    expect(scene.ops.some((o) => o.kind === 'badge')).toBe(false);
    expect(texts(scene.ops).filter((o) => o.el === 'headline')).toHaveLength(1);
    expect(texts(scene.ops).some((o) => o.strike)).toBe(false);
  });

  it('drops feature pills that do not fit', () => {
    const many = ['超長的賣點文字一號', '超長的賣點文字二號', '超長的賣點文字三號', '超長的賣點文字四號'];
    const pills = composePoster(sceneInput(spec, { features: many })).ops.filter((o) => o.kind === 'pill' && o.el === 'features');
    expect(pills.length).toBeGreaterThan(0);
    expect(pills.length).toBeLessThan(many.length);
  });
});

describe('brand logo image', () => {
  const spec = cleanSpec();
  const logoOf = (input: SceneInput) => composePoster(input).ops.find((o): o is LogoOp => o.kind === 'logo')!;

  it('draws the vector mark when the brand has no logo image', () => {
    expect(logoOf(sceneInput(spec)).image).toBeNull();
  });

  it('uses the logo image and keeps the wordmark as the fallback', () => {
    const logo = logoOf({ ...sceneInput(spec), brand: { ...SELUNE, logo: { url: '/files/brands/assets/selune.png' } } });
    expect(logo.image).toBe('/files/brands/assets/selune.png');
    expect(logo.wordmark?.text).toBe('SÉLUNE');
  });

  it('fits the image inside the logo box: same aspect ratio, left aligned and vertically centred', () => {
    const box = { x: 10, y: 20, w: 300, h: 60 };
    expect(fitLogoImage(box, 400, 100)).toEqual({ x: 10, y: 20, w: 240, h: 60 });
    expect(fitLogoImage(box, 1200, 100)).toEqual({ x: 10, y: 37.5, w: 300, h: 25 });
    expect(fitLogoImage(box, 100, 200)).toEqual({ x: 10, y: 20, w: 30, h: 60 });
  });
});

describe('helpers', () => {
  it('logoFor picks a mark and the latin wordmark', () => {
    expect(logoFor({ id: 'selune', name: 'SÉLUNE 晞月' })).toEqual({ mark: 'crescent', wordmark: 'SÉLUNE' });
    expect(logoFor({ id: 'misty-isle', name: '霧嶼咖啡 MISTY ISLE' })).toEqual({ mark: 'isle', wordmark: 'MISTY ISLE' });
    expect(logoFor({ id: 'x', name: '測試品牌' })).toEqual({ mark: 'monogram', wordmark: '測試品牌' });
  });

  it('formatPrice adds thousands separators', () => {
    expect(formatPrice(1280)).toBe('1,280');
    expect(formatPrice(120)).toBe('120');
    expect(formatPrice(1234567)).toBe('1,234,567');
  });
});
