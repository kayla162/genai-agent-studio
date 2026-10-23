import { describe, expect, it } from 'vitest';
import type { Brand, PromptSpec } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { composePoster } from '@/lib/compose/scene';
import { cleanSpec, makeSpec } from '@/test/fixtures';
import { bestMatch, expectedSegments, normalizeOcr, OCR_MIN_PX, ocrCheck, ocrDiffs, type OcrSegment } from './ocr';

const sceneOf = (spec: PromptSpec, brand: Brand = SELUNE) =>
  composePoster({ canvas: spec.canvas, layout: spec.layout, palette: spec.palette, copy: spec.copy, brand });
const segmentsOf = (spec: PromptSpec, brand: Brand = SELUNE) => expectedSegments(sceneOf(spec, brand));
/** 轉錄結果：每段預期文字一行（與海報上完全相同） */
const linesOf = (segments: OcrSegment[]) => segments.map((s) => s.text);

describe('normalizeOcr', () => {
  it('folds width and case, and drops spaces, punctuation and symbols', () => {
    expect(normalizeOcr('ＮＴ$ 1,280')).toBe('nt1280');
    expect(normalizeOcr('7天感受透亮光采・專業修護配方*')).toBe('7天感受透亮光采專業修護配方');
    expect(normalizeOcr('BUY 1 GET 1')).toBe('buy1get1');
  });

  it('keeps the box and the unreadable marker', () => {
    expect(normalizeOcr('醒來□亮？')).toBe('醒來□亮?');
  });
});

describe('bestMatch', () => {
  it('finds the closest substring anywhere in the transcription', () => {
    expect(bestMatch('透亮', '醒來透亮發光')).toEqual({ distance: 0, read: '透亮' });
    expect(bestMatch('醒來透亮發光', 'ab醒來透高發光cd')).toEqual({ distance: 1, read: '醒來透高發光' });
  });

  it('counts a missing or an extra character as one difference', () => {
    expect(bestMatch('醒來透亮發光', 'x醒來透發光y').distance).toBe(1);
    expect(bestMatch('醒來透亮發光', '醒來透亮亮發光').distance).toBe(1);
  });

  it('reports the whole text as different when nothing was read', () => {
    expect(bestMatch('透亮', '')).toEqual({ distance: 2, read: '' });
  });
});

describe('expectedSegments', () => {
  it('lists every drawn text with its element and font size', () => {
    const segments = segmentsOf(makeSpec());
    const texts = linesOf(segments);
    for (const text of [
      'SÉLUNE', '一夜溫柔修護', '醒來透亮發光', '7天感受透亮光采・專業修護配方*', '5重玻尿酸', '週年慶限定', '買一送一',
      'BUY 1 GET 1', '極光玻尿酸修護精華 30ml｜週年慶活動價', 'NT$', '1,280', '原價 NT$1,680',
    ]) expect(texts).toContain(text);
    expect(segments.find((s) => s.text === '醒來透亮發光')).toMatchObject({ el: 'headline' });
    expect(segments.every((s) => s.size > 0)).toBe(true);
  });

  it('includes the call to action on wide price boxes', () => {
    expect(linesOf(segmentsOf(cleanSpec(SELUNE, undefined, 'banner')))).toContain('立即選購 →');
  });

  it('leaves out the wordmark when the brand logo image is drawn', () => {
    const withLogo = { ...SELUNE, logo: { url: '/files/brands/selune/logo.png' } };
    expect(linesOf(segmentsOf(makeSpec(), withLogo))).not.toContain('SÉLUNE');
  });
});

describe('ocrDiffs', () => {
  const segments = segmentsOf(makeSpec());

  it('passes when the transcription matches, regardless of line breaks and extra text', () => {
    const lines = [linesOf(segments).reverse().join(''), '極光玻尿酸 修護精華（瓶身文字）'];
    const result = ocrDiffs(lines, segments, 1);
    expect(result).toMatchObject({ diffs: 0, boxes: false, worst: null, skipped: 0 });
    expect(result.compared).toBe(segments.length);
    expect(ocrCheck(result)).toEqual({ value: '0 處差異', status: 'pass', target: 'headline' });
  });

  it('warns about one misread character in the headline', () => {
    const lines = linesOf(segments).map((t) => (t === '醒來透亮發光' ? '醒來透高發光' : t));
    const result = ocrDiffs(lines, segments, 1);
    expect(result.diffs).toBe(1);
    expect(result.worst).toEqual({ el: 'headline', expected: '醒來透亮發光', read: '醒來透高發光', distance: 1 });
    expect(ocrCheck(result)).toEqual({
      value: '1 處差異（標題「醒來透亮發光」讀成「醒來透高發光」）', status: 'warn', target: 'headline',
    });
  });

  it('fails on two differences and targets the element with the most', () => {
    const lines = linesOf(segments).map((t) => ({ 一夜溫柔修護: '一夜溫桑修護', 買一送一: '買二送二' })[t] ?? t);
    const result = ocrDiffs(lines, segments, 1);
    expect(result.diffs).toBe(3);
    expect(ocrCheck(result)).toMatchObject({ status: 'fail', target: 'badge' });
  });

  it('fails when the poster shows boxes for missing glyphs', () => {
    const result = ocrDiffs([...linesOf(segments), '□□'], segments, 1);
    expect(result.boxes).toBe(true);
    expect(ocrCheck(result)).toEqual({ value: '畫面有無法顯示的字（方塊）', status: 'fail', target: 'canvas' });
    const both = ocrDiffs(linesOf(segments).map((t) => (t === '買一送一' ? '買□送一' : t)), segments, 1);
    expect(ocrCheck(both)).toEqual({
      value: '1 處差異（徽章「買一送一」讀成「買□送一」）・畫面有無法顯示的字（方塊）', status: 'fail', target: 'badge',
    });
  });

  it('skips texts that are too small on the image sent to the VLM', () => {
    const scale = 0.5;
    const small = segments.filter((s) => s.size * scale < OCR_MIN_PX);
    expect(small.length).toBeGreaterThan(0);
    const lines = linesOf(segments).filter((t) => !small.some((s) => s.text === t));
    const result = ocrDiffs(lines, segments, scale);
    expect(result).toMatchObject({ diffs: 0, skipped: small.length, compared: segments.length - small.length });
  });

  it('reports a text the VLM did not read at all', () => {
    const lines = linesOf(segments).filter((t) => t !== '一夜溫柔修護');
    expect(ocrCheck(ocrDiffs(lines, segments, 1)).value).toMatch(/^\d+ 處差異（標題「一夜溫柔修護」/);
  });
});

describe('ocrCheck', () => {
  it('keeps the simulated result when there is no transcription', () => {
    expect(ocrCheck(undefined)).toEqual({ value: '0 處差異', status: 'pass', target: 'headline' });
  });
});
