import { describe, expect, it } from 'vitest';
import { TONES, type BBox, type Brand, type LayoutElementId, type Product, type TemplateId } from '@/types/contract';
import type { GuardCode, SpecDraft } from '@/types/agent';
import { MISTY_ISLE, SAMPLE_PRODUCTS, SELUNE } from '@/lib/api/mock/data';
import { parseBrief } from '@/lib/api/mock/brief';
import { computeLayout } from '@/lib/compose/layout';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { finalizeSpec, type GuardRequest } from './guard';
import { buildCopy, buildInjection, buildPromptSpec, negativePromptOf, positivePromptOf } from './prompt';

const SERUM = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_selune_serum')!;
const COLDBREW = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;
const TEXT = '週年慶 2026/10/15–11/15 主打買一送一，溫柔療癒';
const SCENE = 'serum bottle on a pearl tray with soft aurora light';

/** brands/my-brand-01.yaml（Kayla 精緻少女）中與護欄有關的欄位 */
const KAYLA: Brand = {
  ...SELUNE,
  id: 'my-brand-01',
  name: 'Kayla 精緻少女',
  palette: { primary: '#B8A5D6', secondary: '#F9F4E8', accent: '#C9A96E', ink: '#3A3335' },
  visualStyle: 'warm minimal product photography, natural linen texture, soft morning light',
  defaultTone: 'science',
  claimWords: ['修護', '改善'],
  copyPresets: {
    gentle: { headline: ['溫柔呵護', '每一天'], subhead: '天然成分・溫和配方' },
    science: { headline: ['科學配方', '看得見的改變'], subhead: '專利成分・臨床測試' },
    playful: { headline: ['今天也要', '閃閃發光！'], subhead: '限時優惠，手刀搶購' },
    minimal: { headline: ['簡單', '就是美'], subhead: '純粹成分・無多餘添加' },
  },
};
const KAYLA_PRODUCT: Product = { ...SERUM, id: 'prod_kayla', brandId: KAYLA.id, name: 'Kayla 玻尿酸精華' };

function request(over: Partial<GuardRequest> = {}): GuardRequest {
  const brand = over.brand ?? SELUNE;
  const product = over.product ?? SERUM;
  const text = over.text ?? TEXT;
  return {
    jobId: 'job_g', round: 1, brand, product, brief: parseBrief(text, brand, product), text, templateId: 'ig-post',
    engine: 'comfyui', seed: 42, ragRefs: ['selune#color', 'selune#law'], fixes: [], ...over,
  };
}

/** 與模擬版相同的文案與預設版型：護欄不會有任何意見 */
function goodDraft(req: GuardRequest = request()): SpecDraft {
  const spec = buildPromptSpec({ ...req, template: getTemplate(req.templateId) });
  const { copy } = spec;
  return {
    headline: [...copy.headline], subhead: copy.subhead, features: [...copy.features], badge: { ...copy.badge },
    priceLabel: copy.price.label, layout: spec.layout.map((b) => ({ id: b.id, bbox: [...b.bbox] })), scene: SCENE,
    negativeExtra: '', rationale: '商品放右下，標題靠左對齊網格',
  };
}

const codes = (issues: { code: GuardCode; field: string }[]) => issues.map((i) => `${i.code}@${i.field}`);
const setBox = (draft: SpecDraft, id: LayoutElementId, bbox: BBox) => {
  draft.layout = draft.layout.map((b) => (b.id === id ? { id, bbox } : b));
};

describe('finalizeSpec: a compliant draft', () => {
  it('keeps the copy and layout, and fills in what the program decides', () => {
    const req = request();
    const expected = buildPromptSpec({ ...req, template: getTemplate('ig-post') });
    const { spec, issues } = finalizeSpec(goodDraft(req), req);
    expect(issues).toEqual([]);
    expect(spec.copy).toEqual(expected.copy);
    expect(spec.layout).toEqual(expected.layout);
    expect(spec.layout.map((b) => [b.id, b.z])).toEqual([
      ['logo', 2], ['headline', 2], ['subhead', 2], ['features', 2], ['product', 1], ['badge', 3], ['price', 2], ['disclaimer', 2],
    ]);
    expect(spec.palette).toEqual(SELUNE.palette);
    expect(spec.positivePrompt).toBe(positivePromptOf(getTemplate('ig-post'), SELUNE, req.brief, SCENE));
    expect(spec.negativePrompt).toBe(negativePromptOf([]));
    expect(spec.injection).toEqual(buildInjection(spec, 'comfyui', SERUM.id, 42));
    expect(spec.ragRefs).toEqual(['selune#color', 'selune#law']);
    expect([spec.jobId, spec.round, spec.templateId, spec.brandId]).toEqual(['job_g', 1, 'ig-post', 'selune']);
  });
});

describe('finalizeSpec: copy', () => {
  it('applies the brand replacements every round without reporting them', () => {
    const draft = goodDraft();
    draft.subhead = '7天根治暗沉・醫療級修護';
    const { spec, issues } = finalizeSpec(draft, request());
    expect(spec.copy.subhead).toBe('7天改善外觀暗沉・專業配方修護');
    expect(issues).toEqual([]);
  });

  it('removes emoji without asking again', () => {
    const draft = goodDraft();
    draft.headline[1] = '醒來透亮發光✨';
    const { spec, issues } = finalizeSpec(draft, request());
    expect(spec.copy.headline[1]).toBe('醒來透亮發光');
    expect(issues).toEqual([{ code: 'emoji_removed', field: 'headline.1', message: expect.stringContaining('✨'), retry: false }]);
  });

  it('asks again about characters the poster fonts lack, and falls back to the default copy', () => {
    const draft = goodDraft();
    draft.headline[0] = '这一夜修護';
    const { spec, issues } = finalizeSpec(draft, request());
    expect(issues).toEqual([{
      code: 'missing_glyph', field: 'headline.0', retry: true,
      message: '標題第 1 行「这一夜修護」有伺服器字型沒有的字：「这」，請改用繁體字或其他寫法',
    }]);
    expect(spec.copy.headline).toEqual(['一夜溫柔修護', '醒來透亮發光']);
  });

  it('asks again about banned words the replacements do not cover', () => {
    const brand = { ...SELUNE, bannedWords: [...SELUNE.bannedWords, '奇蹟'] };
    const draft = goodDraft();
    draft.subhead = '奇蹟般的透亮光采';
    const { spec, issues } = finalizeSpec(draft, request({ brand }));
    expect(codes(issues)).toEqual(['banned_word@subhead']);
    expect(issues[0].message).toContain('「奇蹟」');
    expect(spec.copy.subhead).toBe(SELUNE.copyPresets.gentle.subhead);
  });

  it('asks again about copy that is too long, and upper-cases the badge English', () => {
    const draft = goodDraft();
    draft.headline[1] = '醒來透亮發光醒來透亮';
    draft.subhead = '七天感受透亮光采・專業修護配方・七天感受透亮光采';
    draft.features = ['5重玻尿酸', '神經醯胺與五重玻尿酸雙效保濕'];
    draft.badge.sub = 'buy one get one';
    const { spec, issues } = finalizeSpec(draft, request());
    expect(codes(issues)).toEqual(['too_long@headline.1', 'too_long@subhead', 'too_long@features.1']);
    expect(spec.copy.badge.sub).toBe('BUY ONE GET ONE');
    expect(spec.copy.features).toEqual(['5重玻尿酸', '神經醯胺', '無香精']);

    const chinese = goodDraft();
    chinese.badge.sub = '買一送一';
    expect(codes(finalizeSpec(chinese, request()).issues)).toEqual(['too_long@badge.sub']);
  });

  it('fixes the badge to the offer and rejects prices or offers the brief does not mention', () => {
    const offered = goodDraft();
    offered.badge.main = '特價';
    expect(finalizeSpec(offered, request()).spec.copy.badge.main).toBe('買一送一');

    const text = '溫柔療癒的保養海報，新品價 NT$990';
    const req = request({ text });
    const draft = goodDraft(req);
    draft.badge.main = '8折';
    draft.subhead = '新品價 NT$990 溫柔上市';
    draft.features = ['買二送一'];
    draft.priceLabel = '20%回饋價';
    const { spec, issues } = finalizeSpec(draft, req);
    expect(codes(issues)).toEqual(['invented_offer@features.0', 'invented_offer@badge.main', 'invented_offer@priceLabel']);
    expect(issues[1].message).toContain('「8折」');
    expect(spec.copy.subhead).toBe('新品價 NT$990 溫柔上市');
    expect(spec.copy.badge.main).toBe('限時優惠');
    expect(spec.copy.price.label).toBe('限時活動價');
  });

  it('asks again about empty headline lines', () => {
    const draft = goodDraft();
    draft.headline = ['  ', '醒來透亮發光'];
    expect(codes(finalizeSpec(draft, request()).issues)).toEqual(['empty_field@headline.0']);
  });

  it('keeps the product name as user data: emoji removed, missing glyphs only reported', () => {
    const product = { ...SERUM, name: '極光精華✨这款' };
    const { spec, issues } = finalizeSpec(goodDraft(request({ product })), request({ product }));
    expect(spec.copy.productName).toBe('極光精華这款');
    expect(issues.map((i) => [i.code, i.field, i.retry])).toEqual([
      ['emoji_removed', 'productName', false], ['product_glyph', 'productName', false],
    ]);
  });

  it('computes the disclaimer from the final copy', () => {
    const draft = goodDraft();
    draft.headline = ['一夜好眠', '醒來發光'];
    draft.subhead = '專業配方';
    draft.features = [];
    const { spec } = finalizeSpec(draft, request());
    expect(spec.copy.disclaimer).toBe('活動期間 2026/10/15–11/15｜數量有限，售完為止');
    expect(spec.copy.features).toEqual([]);
  });
});

describe('finalizeSpec: layout', () => {
  const defaultLayout = computeLayout(getTemplate('ig-post'));

  it.each([
    ['a missing element', (d: SpecDraft) => { d.layout = d.layout.filter((b) => b.id !== 'price'); }, '版面缺少元素：價格'],
    ['a duplicated element', (d: SpecDraft) => { d.layout[7] = { ...d.layout[1] }; }, '「標題」出現 2 次'],
    ['fractions', (d: SpecDraft) => setBox(d, 'logo', [100.5, 90, 374, 81]), '「Logo」的方框必須是 4 個整數'],
    ['a box outside the canvas', (d: SpecDraft) => setBox(d, 'product', [634, 720, 900, 918]), '「商品」的方框超出畫布（1440 × 1800）'],
    ['overlapping boxes', (d: SpecDraft) => setBox(d, 'badge', [600, 846, 346, 346]), '「商品」與「徽章」的方框重疊'],
  ])('rejects %s and falls back to the default layout', (_, mutate, message) => {
    const draft = goodDraft();
    mutate(draft);
    const { spec, issues } = finalizeSpec(draft, request());
    expect(codes(issues)).toEqual(['layout_invalid@layout']);
    expect(issues[0].message).toContain(message);
    expect(spec.layout).toEqual(defaultLayout);
  });

  it('checks the brand layout rules with the review functions', () => {
    const brand = { ...SELUNE, rules: { ...SELUNE.rules, productRatio: [0.4, 0.6] as [number, number] } };
    const { spec, issues } = finalizeSpec(goodDraft(request({ brand })), request({ brand }));
    expect(issues).toEqual([{ code: 'layout_rule', field: 'layout', retry: true, message: '商品框佔畫面 25.5%，品牌規範為 40%–60%' }]);
    expect(spec.layout).toEqual(defaultLayout);

    const crowded = goodDraft();
    setBox(crowded, 'headline', [101, 180, 864, 288]);
    setBox(crowded, 'logo', [126, 90, 374, 81]);
    expect(finalizeSpec(crowded, request()).issues[0].message).toMatch(/^Logo 與標題的間距 9px，需 ≥ 0\.5 × Logo 高（41px）/);
  });

  it('asks again when the layout makes the text too small', () => {
    const draft = goodDraft();
    setBox(draft, 'headline', [101, 216, 864, 30]);
    const { spec, issues } = finalizeSpec(draft, request());
    expect(codes(issues)).toEqual(['text_too_small@layout']);
    expect(issues[0].message).toContain('標題的字級只有 12.5px');
    expect(spec.layout).toEqual(defaultLayout);
  });
});

describe('finalizeSpec: prompts', () => {
  it('rejects a scene that is not English and uses the simulated prompt', () => {
    const req = request();
    const draft = goodDraft(req);
    draft.scene = '珍珠托盤上的精華液';
    draft.negativeExtra = '雜亂';
    const { spec, issues } = finalizeSpec(draft, req);
    expect(codes(issues)).toEqual(['prompt_invalid@scene', 'prompt_invalid@negativeExtra']);
    expect(spec.positivePrompt).toBe(buildPromptSpec({ ...req, template: getTemplate('ig-post') }).positivePrompt);
    expect(spec.negativePrompt).toBe(negativePromptOf([]));
  });

  it('adds the earlier failures and the extra negative terms once each', () => {
    const req = request({ round: 2, fixes: ['color_delta', 'vlm_quality'] });
    const draft = goodDraft(req);
    draft.negativeExtra = 'neon, plastic look';
    const { spec } = finalizeSpec(draft, req);
    expect(spec.negativePrompt).toBe(negativePromptOf(['color_delta', 'vlm_quality'], 'neon, plastic look'));
    expect(spec.negativePrompt.split(', ').filter((t) => t === 'neon')).toHaveLength(1);
    expect(spec.injection.params.find((p) => p.label === 'negative_prompt')?.value).toBe(spec.negativePrompt);
  });
});

describe('finalizeSpec: the defaults never trip the layout guard', () => {
  const cases: [Brand, Product][] = [[SELUNE, SERUM], [MISTY_ISLE, COLDBREW], [KAYLA, KAYLA_PRODUCT]];
  for (const [brand, product] of cases) {
    for (const tone of TONES) {
      it.each(CHANNEL_TEMPLATES.map((t) => t.id))(`${brand.id} ${tone} %s`, (templateId: TemplateId) => {
        const req = request({ brand, product, templateId });
        const brief = { ...req.brief, tone };
        const copy = buildCopy(brand, product, brief, true);
        const draft: SpecDraft = {
          headline: copy.headline, subhead: copy.subhead, features: copy.features, badge: copy.badge, priceLabel: copy.price.label,
          layout: computeLayout(getTemplate(templateId)).map((b) => ({ id: b.id, bbox: b.bbox })), scene: '', negativeExtra: '',
          rationale: '',
        };
        const { issues } = finalizeSpec(draft, { ...req, brief });
        expect(issues.filter((i) => i.code === 'layout_invalid' || i.code === 'text_too_small')).toEqual([]);
      });
    }
  }
});
