import { describe, it, expect } from 'vitest';
import { TONES } from '@/types/contract';
import { hexToRgb } from '@/lib/review/color';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './index';

describe.each(BRANDS)('brand $id', (brand) => {
  it('has a valid palette', () => {
    for (const hex of Object.values(brand.palette)) expect(() => hexToRgb(hex)).not.toThrow();
  });

  it('has one guideline chunk per tag plus a law-alt chunk, with unique ids', () => {
    const tags = brand.guidelineChunks.map((c) => c.tag);
    for (const tag of ['color', 'logo', 'law', 'layout', 'font', 'history'] as const) expect(tags).toContain(tag);
    const ids = brand.guidelineChunks.map((c) => c.id);
    expect(ids).toContain(`${brand.id}#law-alt`);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('has a two-line copy preset for every tone', () => {
    for (const tone of TONES) {
      expect(brand.copyPresets[tone].headline).toHaveLength(2);
      expect(brand.copyPresets[tone].subhead.length).toBeGreaterThan(0);
    }
  });

  it('only defines replacements for banned words, and presets contain no banned words', () => {
    for (const word of Object.keys(brand.replacements)) expect(brand.bannedWords).toContain(word);
    for (const tone of TONES) {
      const text = brand.copyPresets[tone].headline.join('') + brand.copyPresets[tone].subhead;
      for (const word of brand.bannedWords) expect(text).not.toContain(word);
    }
  });
});

describe('lookups', () => {
  it('finds brands by id and rejects unknown ids', () => {
    expect(getBrandById('selune').name).toBe('SÉLUNE 晞月');
    expect(() => getBrandById('nope')).toThrow('Unknown brand');
  });

  it('every sample product belongs to a known brand', () => {
    expect(SAMPLE_PRODUCTS.length).toBeGreaterThanOrEqual(2);
    for (const p of SAMPLE_PRODUCTS) expect(() => getBrandById(p.brandId)).not.toThrow();
  });
});
