import { describe, it, expect } from 'vitest';
import { mulberry32 } from '@/lib/core/num';
import { hexToRgb, rgbToHex, mixHex, rgbToLab, labToHex, deltaE2000, deltaEHex } from './color';

describe('hex conversion', () => {
  it('parses and formats hex colors', () => {
    expect(hexToRgb('#B76E79')).toEqual([183, 110, 121]);
    expect(rgbToHex([183, 110, 121])).toBe('#b76e79');
  });

  it('throws on invalid hex', () => {
    expect(() => hexToRgb('#12345')).toThrow('Invalid hex color');
  });

  it('mixes two colors', () => {
    expect(mixHex('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixHex('#B76E79', '#ffffff', 0)).toBe('#b76e79');
  });
});

describe('rgbToLab (D65)', () => {
  it('converts white, black and pure red', () => {
    const white = rgbToLab([255, 255, 255]);
    expect(white.L).toBeCloseTo(100, 1);
    expect(white.a).toBeCloseTo(0, 1);
    expect(white.b).toBeCloseTo(0, 1);
    expect(rgbToLab([0, 0, 0]).L).toBeCloseTo(0, 1);
    const red = rgbToLab([255, 0, 0]);
    expect(red.L).toBeCloseTo(53.24, 1);
    expect(red.a).toBeCloseTo(80.09, 1);
    expect(red.b).toBeCloseTo(67.2, 1);
  });
});

describe('labToHex', () => {
  it('inverts rgbToLab for every 8-bit grey and a deterministic sample of colours', () => {
    const colours: [number, number, number][] = [[0, 0, 0], [255, 255, 255], [183, 110, 121], [30, 136, 229]];
    for (let v = 0; v < 256; v++) colours.push([v, v, v]);
    const rng = mulberry32(7);
    for (let i = 0; i < 2000; i++) colours.push([0, 1, 2].map(() => Math.floor(rng() * 256)) as [number, number, number]);
    for (const rgb of colours) expect(labToHex(rgbToLab(rgb))).toBe(rgbToHex(rgb));
  });

  it('clamps colours outside the sRGB gamut', () => {
    expect(labToHex({ L: 50, a: 127, b: -127 })).toMatch(/^#[0-9a-f]{6}$/);
    expect(labToHex({ L: 120, a: 0, b: 0 })).toBe('#ffffff');
  });
});

describe('deltaE2000', () => {
  // Sharma, Wu & Dalal (2005) CIEDE2000 測試資料
  it.each([
    [{ L: 50, a: 2.6772, b: -79.7751 }, { L: 50, a: 0, b: -82.7485 }, 2.0425],
    [{ L: 50, a: 3.1571, b: -77.2803 }, { L: 50, a: 0, b: -82.7485 }, 2.8615],
    [{ L: 50, a: 0, b: 0 }, { L: 50, a: -1, b: 2 }, 2.3669],
    [{ L: 50, a: 2.5, b: 0 }, { L: 73, a: 25, b: -18 }, 27.1492],
  ])('matches reference pair %#', (x, y, expected) => {
    expect(deltaE2000(x, y)).toBeCloseTo(expected, 3);
  });

  it('is zero for identical colors and symmetric', () => {
    const c = { L: 62, a: 24, b: 3 };
    expect(deltaE2000(c, c)).toBe(0);
    const d = { L: 40, a: -10, b: 30 };
    expect(deltaE2000(c, d)).toBeCloseTo(deltaE2000(d, c), 10);
  });

  it('deltaEHex flags an off-brand pink as far from the brand rose', () => {
    expect(deltaEHex('#B76E79', '#B76E79')).toBe(0);
    expect(deltaEHex('#E0458A', '#B76E79')).toBeGreaterThan(5);
    expect(deltaEHex(mixHex('#B76E79', '#ffffff', 0.03), '#B76E79')).toBeLessThan(5);
  });
});
