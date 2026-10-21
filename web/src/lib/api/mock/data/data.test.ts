import { describe, it, expect } from 'vitest';
import { TONES } from '@/types/contract';
import { hexToRgb } from '@/lib/review/color';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS, SELUNE } from './index';

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

  it('lists every case study as a chunk after the guidelines and before the law-alt chunk', () => {
    const cases = brand.caseStudies.map((_, i) => `${brand.id}#case-${i + 1}`);
    expect(brand.guidelineChunks.slice(-cases.length - 1).map((c) => c.id)).toEqual([...cases, `${brand.id}#law-alt`]);
    // 模擬檢索取每個標籤的第一個切塊：history 仍是設定檔的成效摘要，mock 劇本不變
    expect(brand.guidelineChunks.find((c) => c.tag === 'history')!.id).toBe(`${brand.id}#history`);
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

describe('case-study chunks', () => {
  it('follow the backend rule for the id, source, section, tag and text', () => {
    expect(SELUNE.guidelineChunks.find((c) => c.id === 'selune#case-2')).toEqual({
      id: 'selune#case-2', source: 'selune.yaml', section: '夏季保濕電商主圖', tag: 'history',
      text: '電商主圖素材，CTR 3.1%：淺色背景 + 水珠，強調長效保濕',
    });
  });
});

describe('mock data immutability', () => {
  it('is frozen so shared demo data cannot be mutated', () => {
    expect(Object.isFrozen(SELUNE.palette)).toBe(true);
    expect(Object.isFrozen(SAMPLE_PRODUCTS[0].price)).toBe(true);
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
