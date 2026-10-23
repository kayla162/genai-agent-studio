import { describe, it, expect } from 'vitest';
import type { PromptSpec, ReviewCheck } from '@/types/contract';
import type { VlmVerdict } from '@/types/agent';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { applyFlaws, FLAWS } from '@/lib/api/mock/flaws';
import { mockVlmChecks } from '@/lib/api/mock/vlm';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { cleanSpec } from '@/test/fixtures';
import { runRuleChecks } from './rules';
import { contentVlmChecks, geminiVlmChecks, SIMULATED_VLM_NOTE } from './vlm';

const byId = (checks: ReviewCheck[], id: ReviewCheck['id']) => checks.find((c) => c.id === id)!;
const box = (spec: PromptSpec, id: 'logo' | 'headline') => spec.layout.find((b) => b.id === id)!;

describe('contentVlmChecks', () => {
  it('passes clean specs on every template and marks every result as simulated', () => {
    for (const t of CHANNEL_TEMPLATES) {
      const checks = contentVlmChecks(cleanSpec(SELUNE, undefined, t.id), SELUNE);
      expect(checks.map((c) => [c.id, c.kind, c.status])).toEqual([
        ['vlm_exaggeration', 'vlm', 'pass'], ['vlm_occlusion', 'vlm', 'pass'], ['vlm_quality', 'vlm', 'pass'],
      ]);
      expect(checks.every((c) => c.value.endsWith(SIMULATED_VLM_NOTE))).toBe(true);
    }
    expect(contentVlmChecks(cleanSpec(), SELUNE)).toEqual([
      {
        id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
        value: '未發現誇大用語（模擬：AGENT_MODE=sim）', status: 'pass', target: null, ragRef: 'selune#law',
      },
      {
        id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊',
        value: '無重疊遮擋（模擬：AGENT_MODE=sim）', status: 'pass', target: null, ragRef: 'selune#logo',
      },
      {
        id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵',
        value: '構圖與畫質良好（模擬：AGENT_MODE=sim）', status: 'pass', target: null, ragRef: null,
      },
    ]);
  });

  it('flags the same banned words and block as the banned_words rule', () => {
    const subhead = applyFlaws(cleanSpec(), ['bannedCopy'], SELUNE);
    const features = cleanSpec();
    features.copy.features = ['根治暗沉'];
    const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;
    const price = cleanSpec(MISTY_ISLE, coldbrew, 'banner');
    price.copy.price.label = '保證提神價';
    for (const [spec, brand] of [[subhead, SELUNE], [features, SELUNE], [price, MISTY_ISLE]] as const) {
      const vlm = byId(contentVlmChecks(spec, brand), 'vlm_exaggeration');
      const rule = byId(runRuleChecks({ brand, spec, measuredPrimary: brand.palette.primary }), 'banned_words');
      expect(vlm.status).toBe('fail');
      expect(rule.status).toBe('fail');
      expect(vlm.target).toBe(rule.target);
      expect(vlm.value).toBe(`${rule.value.replace('禁用詞', '偵測到')}${SIMULATED_VLM_NOTE}`);
    }
    expect(byId(contentVlmChecks(subhead, SELUNE), 'vlm_exaggeration')).toMatchObject({
      value: '偵測到「根治」「醫療級」（模擬：AGENT_MODE=sim）', target: 'subhead',
    });
  });

  it('fails occlusion when the logo box overlaps the headline box', () => {
    const spec = applyFlaws(cleanSpec(), ['logoCrowding'], SELUNE);
    expect(byId(contentVlmChecks(spec, SELUNE), 'vlm_occlusion')).toMatchObject({
      status: 'fail', value: 'Logo 與標題重疊（模擬：AGENT_MODE=sim）', target: 'logo',
    });
  });

  it('passes occlusion when the logo sits beside the headline without overlapping it', () => {
    const spec = cleanSpec();
    const head = box(spec, 'headline');
    const logo = box(spec, 'logo');
    logo.bbox = [head.bbox[0] + head.bbox[2] + 8, head.bbox[1], logo.bbox[2], logo.bbox[3]];
    // 規則的淨空區只看上下距離，所以不通過；遮擋要框真的重疊才算
    expect(byId(runRuleChecks({ brand: SELUNE, spec, measuredPrimary: '#B76E79' }), 'logo_clearance').status).toBe('fail');
    expect(byId(contentVlmChecks(spec, SELUNE), 'vlm_occlusion').status).toBe('pass');
  });

  it('never warns: quality always passes and there are no candidate-scripted warnings', () => {
    const flawed = applyFlaws(cleanSpec(), FLAWS, SELUNE);
    expect(contentVlmChecks(flawed, SELUNE).map((c) => c.status)).toEqual(['fail', 'fail', 'pass']);
    // mock 依候選編號出現警告（variant 1、2），content 版沒有候選編號
    expect(mockVlmChecks(cleanSpec(), SELUNE, 1).some((c) => c.status === 'warn')).toBe(true);
    expect(mockVlmChecks(cleanSpec(), SELUNE, 2).some((c) => c.status === 'warn')).toBe(true);
    expect(contentVlmChecks(cleanSpec(), SELUNE).some((c) => c.status === 'warn')).toBe(false);
  });
});

const passing = (): VlmVerdict => ({
  lines: ['SÉLUNE', '一夜溫柔修護', '醒來透亮發光'],
  exaggeration: { status: 'pass', phrases: [], reason: '' },
  occlusion: { status: 'pass', elements: [], reason: '' },
  quality: { status: 'pass', issues: [], reason: '' },
});

describe('geminiVlmChecks', () => {
  it('passes with the same names and rules as the simulated checks, without the simulated note', () => {
    const checks = geminiVlmChecks(passing(), cleanSpec(), SELUNE);
    expect(checks).toEqual([
      {
        id: 'vlm_exaggeration', name: '誇大／療效用語', kind: 'vlm', rule: 'VLM 判讀海報文字語意',
        value: '未發現誇大用語', status: 'pass', target: null, ragRef: 'selune#law',
      },
      {
        id: 'vlm_occlusion', name: '物件與文字遮擋', kind: 'vlm', rule: 'VLM 判讀元素是否重疊',
        value: '無重疊遮擋', status: 'pass', target: null, ragRef: 'selune#layout',
      },
      {
        id: 'vlm_quality', name: '整體畫質', kind: 'vlm', rule: 'VLM 判讀構圖、光線與瑕疵',
        value: '構圖與畫質良好', status: 'pass', target: null, ragRef: null,
      },
    ]);
    expect(checks.map((c) => c.name)).toEqual(contentVlmChecks(cleanSpec(), SELUNE).map((c) => c.name));
    expect(checks.some((c) => c.value.includes('模擬'))).toBe(false);
  });

  it('points an exaggeration at the first block that contains the phrase', () => {
    const spec = cleanSpec();
    spec.copy.subhead = '三天見效・全台第一';
    const verdict = passing();
    verdict.exaggeration = { status: 'fail', phrases: ['三天見效', '全台第一'], reason: '保證效果與誇大排名' };
    expect(byId(geminiVlmChecks(verdict, spec, SELUNE), 'vlm_exaggeration')).toMatchObject({
      status: 'fail', value: '偵測到「三天見效」「全台第一」：保證效果與誇大排名', target: 'subhead', ragRef: 'selune#law',
    });
    verdict.exaggeration = { status: 'warn', phrases: ['奇蹟'], reason: '語意誇大' };
    expect(byId(geminiVlmChecks(verdict, spec, SELUNE), 'vlm_exaggeration')).toMatchObject({ status: 'warn', target: null });
    verdict.exaggeration = { status: 'warn', phrases: [], reason: '整體語氣過度保證' };
    expect(byId(geminiVlmChecks(verdict, spec, SELUNE), 'vlm_exaggeration').value).toBe('整體語氣過度保證');
  });

  it('names the occluded element and cites the logo rule only when the logo is involved', () => {
    const verdict = passing();
    verdict.occlusion = { status: 'fail', elements: ['logo', 'headline'], reason: 'Logo 壓在標題上' };
    expect(byId(geminiVlmChecks(verdict, cleanSpec(), SELUNE), 'vlm_occlusion')).toMatchObject({
      status: 'fail', value: 'Logo：Logo 壓在標題上', target: 'logo', ragRef: 'selune#logo',
    });
    verdict.occlusion = { status: 'warn', elements: ['price', 'product'], reason: '價格與商品重疊' };
    expect(byId(geminiVlmChecks(verdict, cleanSpec(), SELUNE), 'vlm_occlusion')).toMatchObject({
      value: '價格：價格與商品重疊', target: 'price', ragRef: 'selune#layout',
    });
  });

  it('lists the quality issues, or the reason when there are none, and shortens long reasons', () => {
    const verdict = passing();
    verdict.quality = { status: 'warn', issues: ['高光過曝', '商品邊緣模糊'], reason: '光線' };
    expect(byId(geminiVlmChecks(verdict, cleanSpec(), SELUNE), 'vlm_quality')).toMatchObject({
      status: 'warn', value: '高光過曝、商品邊緣模糊', target: null, ragRef: null,
    });
    verdict.quality = { status: 'fail', issues: [], reason: '很'.repeat(80) };
    expect(byId(geminiVlmChecks(verdict, cleanSpec(), SELUNE), 'vlm_quality').value).toBe(`${'很'.repeat(60)}…`);
  });
});
