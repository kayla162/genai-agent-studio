import { describe, it, expect } from 'vitest';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';

const serum = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;

describe('parseBrief', () => {
  it('parses the spec demo sentence for cold brew', () => {
    expect(parseBrief('幫我設計一款簡約風格的冷萃咖啡宣傳海報', MISTY_ISLE, coldbrew)).toEqual({
      productName: '單一產區冷萃咖啡 330ml',
      sellingPoints: ['18小時冷萃', '單一產區', '無添加糖'],
      audience: '一般消費者',
      tone: 'minimal',
      campaign: null,
      offer: null,
      period: null,
      style: ['minimal'],
    });
  });

  it('extracts the campaign period and normalises the separator', () => {
    expect(parseBrief('雙11 11/1–11/11 全館85折', SELUNE, serum).period).toBe('11/1–11/11');
    expect(parseBrief('週年慶 2026/10/15 ~ 11/15 買一送一', SELUNE, serum).period).toBe('2026/10/15–11/15');
    expect(parseBrief('週年慶 10/15 至 11/15', SELUNE, serum).period).toBe('10/15–11/15');
    expect(parseBrief('週年慶買一送一', SELUNE, serum).period).toBeNull();
  });

  it('extracts campaign, offer, tone and style for skincare', () => {
    const b = parseBrief('週年慶檔期主打買一送一，強調保濕與透亮，整體調性溫柔療癒、有高級感。', SELUNE, serum);
    expect(b.tone).toBe('gentle');
    expect(b.campaign).toBe('週年慶');
    expect(b.offer).toBe('買一送一');
    expect(b.style).toEqual(['premium', 'soft', 'healing']);
  });

  it('extracts audience, normalises offers and falls back to the brand tone', () => {
    const b = parseBrief('針對 25 歲上班族，中秋節第二件 6 折，清新一點', SELUNE, serum);
    expect(b.audience).toBe('25 歲上班族');
    expect(b.campaign).toBe('中秋');
    expect(b.offer).toBe('第二件6折');
    expect(b.style).toEqual(['fresh']);
    expect(b.tone).toBe(SELUNE.defaultTone);
  });

  it('puts features mentioned in the brief first', () => {
    expect(parseBrief('主打無香精', SELUNE, serum).sellingPoints).toEqual(['無香精', '5重玻尿酸', '神經醯胺']);
    expect(parseBrief('隨便', SELUNE, null)).toMatchObject({ productName: null, sellingPoints: [] });
  });
});
