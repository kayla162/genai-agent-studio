import { describe, it, expect } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE, MISTY_ISLE } from '@/lib/api/mock/data';
import { makeSpec } from '@/test/fixtures';
import {
  bannedWordHits, findBannedWords, hasClaim, measuredPrimaryOf, NO_PRIMARY_MESSAGE, ragRefFor, runRuleChecks, scoreChecks,
} from './rules';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;

describe('text rules', () => {
  it('finds banned words in list order', () => {
    expect(findBannedWords(['7天根治暗沉・醫療級修護'], SELUNE.bannedWords)).toEqual(['根治', '醫療級']);
    expect(findBannedWords(['一夜溫柔修護'], SELUNE.bannedWords)).toEqual([]);
  });

  it('detects effect claims', () => {
    expect(hasClaim(['醒來透亮發光'], SELUNE.claimWords)).toBe(true);
    expect(hasClaim(['一口清醒'], MISTY_ISLE.claimWords)).toBe(false);
  });

  it('bannedWordHits returns the banned words and the first block that contains one', () => {
    const spec = makeSpec();
    expect(bannedWordHits(spec, SELUNE)).toEqual({ words: [], target: null });
    spec.copy.features = ['醫療級配方'];
    spec.copy.disclaimer = '永久有效';
    expect(bannedWordHits(spec, SELUNE)).toEqual({ words: ['醫療級', '永久'], target: 'features' });
  });

  it('ragRefFor skips the law-alt chunk', () => {
    expect(ragRefFor(SELUNE, 'law')).toBe('selune#law');
  });
});

describe('runRuleChecks', () => {
  it('passes all 7 rule checks for a compliant spec', () => {
    const checks = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#B76E79' });
    expect(checks.map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
    ]);
    expect(checks.every((c) => c.status === 'pass' && c.kind === 'rule')).toBe(true);
  });

  it('fails banned words and points at the subhead', () => {
    const spec = makeSpec();
    spec.copy.subhead = '7天根治暗沉・醫療級修護';
    const c = byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'banned_words');
    expect(c.status).toBe('fail');
    expect(c.target).toBe('subhead');
    expect(c.value).toBe('禁用詞「根治」「醫療級」');
  });

  it('fails the color check for an off-brand pink', () => {
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#E0458A' }), 'color_delta');
    expect(c.status).toBe('fail');
    expect(c.value).toContain('#E0458A');
  });

  it('fails the color check when no primary could be measured, leaving the other rules alone', () => {
    const spec = makeSpec();
    const none = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: null });
    expect(byId(none, 'color_delta')).toEqual({
      id: 'color_delta', name: '品牌主色色差', kind: 'rule', rule: 'ΔE2000 ≤ 5',
      value: '未偵測到主色（主色區塊 < 2%）', status: 'fail', target: 'canvas', ragRef: 'selune#color',
    });
    expect(NO_PRIMARY_MESSAGE).toBe('未偵測到主色（主色區塊 < 2%）');
    const measured = runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' });
    expect(none.filter((c) => c.id !== 'color_delta')).toEqual(measured.filter((c) => c.id !== 'color_delta'));
  });

  it('reports the measured primary in upper case with its ΔE', () => {
    const c = byId(runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#b76f7a' }), 'color_delta');
    expect(c).toMatchObject({ status: 'pass', value: 'ΔE 0.3 · 偵測主色 #B76F7A' });
  });

  it('measuredPrimaryOf reads the measured primary back from the colour check, for the swatch', () => {
    const checks = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#e0458a' });
    expect(measuredPrimaryOf(byId(checks, 'color_delta'))).toBe('#E0458A');
    expect(byId(checks, 'color_delta').status).toBe('fail');
    // 量不到主色、其他檢查的說明，都沒有色塊
    const none = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: null });
    expect(measuredPrimaryOf(byId(none, 'color_delta'))).toBeNull();
    expect(checks.filter((c) => c.id !== 'color_delta').map(measuredPrimaryOf)).toEqual(Array(checks.length - 1).fill(null));
    expect(measuredPrimaryOf({ id: 'banned_words', value: '偵測主色 #B76F7A' })).toBeNull();
    expect(measuredPrimaryOf({ id: 'color_delta', value: 'ΔE 2 · 偵測主色 #B76F7' })).toBeNull();
  });

  it('fails logo clearance when the logo is pushed into the headline', () => {
    const spec = makeSpec();
    const logo = spec.layout.find((b) => b.id === 'logo')!;
    const head = spec.layout.find((b) => b.id === 'headline')!;
    logo.bbox[1] = head.bbox[1] - Math.round(logo.bbox[3] * 0.55);
    const c = byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'logo_clearance');
    expect(c.status).toBe('fail');
    expect(c.value).toBe('與標題重疊 36px');
  });

  it('warns when an effect claim has no disclaimer; brands without claims pass', () => {
    const spec = makeSpec();
    spec.copy.disclaimer = '活動期間 2026/10/15–11/15';
    expect(byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'disclaimer').status).toBe('warn');

    const coffee = makeSpec({ brandId: MISTY_ISLE.id, palette: { ...MISTY_ISLE.palette } });
    coffee.copy.headline = ['一口清醒', '慢萃十八小時'];
    coffee.copy.subhead = '單一產區耶加雪菲・低溫冷萃 18 小時';
    coffee.copy.disclaimer = '圖片僅供參考';
    const checks = runRuleChecks({ brand: MISTY_ISLE, spec: coffee, measuredPrimary: '#2F4A44' });
    expect(byId(checks, 'disclaimer').value).toBe('無效果宣稱');
    expect(checks.every((c) => c.status === 'pass')).toBe(true);
  });

  it('warns about one OCR difference and fails on boxes', () => {
    const one = { diffs: 1, boxes: false, worst: { el: 'subhead', expected: '7天', read: '1天', distance: 1 }, compared: 9, skipped: 0 } as const;
    const checks = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#B76E79', ocr: one });
    expect(byId(checks, 'ocr_typo')).toMatchObject({ status: 'warn', target: 'subhead', value: '1 處差異（副標「7天」讀成「1天」）' });
    expect(scoreChecks(checks)).toEqual({ score: 94, passed: true });

    const boxes = { diffs: 0, boxes: true, worst: null, compared: 9, skipped: 0 };
    const failed = runRuleChecks({ brand: SELUNE, spec: makeSpec(), measuredPrimary: '#B76E79', ocr: boxes });
    expect(byId(failed, 'ocr_typo')).toMatchObject({ status: 'fail', target: 'canvas' });
    expect(scoreChecks(failed).passed).toBe(false);
  });

  it('scans the price label and product name for banned words', () => {
    const spec = makeSpec();
    spec.copy.price.label = '保證有效活動價';
    const c = byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'banned_words');
    expect(c.status).toBe('fail');
    expect(c.target).toBe('price');
  });

  it('treats claim words in features as effect claims', () => {
    const spec = makeSpec();
    spec.copy.headline = ['一夜好眠', '醒來發光'];
    spec.copy.subhead = '專業配方';
    spec.copy.features = ['淡化細紋'];
    spec.copy.disclaimer = '活動期間 2026/10/15–11/15';
    expect(byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'disclaimer').status).toBe('warn');
  });
});

describe('scoreChecks', () => {
  const mk = (status: ReviewCheck['status']): ReviewCheck => ({
    id: 'banned_words', name: 'x', kind: 'rule', rule: 'x', value: 'x', status, target: null, ragRef: null,
  });

  it('subtracts 14 per fail, 6 per warn and the jitter', () => {
    expect(scoreChecks([mk('pass'), mk('pass')], 2)).toEqual({ score: 98, passed: true });
    expect(scoreChecks([mk('fail'), mk('fail'), mk('warn')])).toEqual({ score: 66, passed: false });
    expect(scoreChecks(Array.from({ length: 10 }, () => mk('fail'))).score).toBe(0);
  });
});
