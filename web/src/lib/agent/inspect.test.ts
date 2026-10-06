import { describe, expect, it } from 'vitest';
import { makeJobSnapshot } from '@/test/fixtures';
import { applyEvents } from '@/lib/jobs/view';
import { injectionRows, overlayFor, rerankRows, retryDiffs, specOptions } from './inspect';

const { events } = makeJobSnapshot();
const view = applyEvents(events);
const upTo = (type: string) => applyEvents(events.slice(0, events.findIndex((e) => e.type === type) + 1));

describe('specOptions', () => {
  it('orders prompts by round, then by the standard template order', () => {
    const two = applyEvents(makeJobSnapshot({ templateIds: ['story', 'ig-post'] }).events);
    expect(specOptions(two).map((o) => o.key)).toEqual(['1:ig-post', '1:story', '2:ig-post', '2:story']);
  });
});

describe('injectionRows', () => {
  it('has no previous values in the first round', () => {
    const rows = injectionRows(view, '1:ig-post');
    expect(rows).toHaveLength(15);
    expect(rows.every((r) => r.previous === null && !r.changed)).toBe(true);
  });

  it('marks the parameters the rewrite changed', () => {
    const rows = injectionRows(view, '2:ig-post');
    expect(rows.filter((r) => r.changed).map((r) => r.label)).toEqual(['positive_prompt', 'negative_prompt', 'seed', 'layout_boxes']);
    const negative = rows.find((r) => r.label === 'negative_prompt')!;
    expect(negative.previous).toBe('lowres, blurry, watermark, deformed product, extra objects, garbled text');
    expect(String(negative.value)).toContain('off-brand colors');
  });

  it('returns nothing for an unknown prompt', () => {
    expect(injectionRows(view, '9:ig-post')).toEqual([]);
  });
});

describe('rerankRows', () => {
  it('compares vector and rerank ranks and lists the failed checks citing each guideline', () => {
    expect(rerankRows(view).map((r) => [r.tag, r.vectorRank, r.rerankRank, r.citedBy])).toEqual([
      ['color', 2, 1, ['color_delta']],
      ['law', 5, 2, ['banned_words', 'disclaimer', 'vlm_exaggeration']],
      ['logo', 4, 3, ['logo_clearance', 'vlm_occlusion']],
      ['layout', 1, 4, []],
      ['history', 3, 5, []],
    ]);
  });

  it('uses the vector order before rerank arrives', () => {
    const rows = rerankRows(upTo('rag.retrieved'));
    expect(rows.map((r) => r.tag)).toEqual(['layout', 'color', 'history', 'logo', 'law']);
    expect(rows.every((r) => r.rerankRank === null && r.rerankScore === null)).toBe(true);
  });
});

describe('overlayFor', () => {
  it('colours each layout box by the worst check that targets it', () => {
    const first = view.renders[view.renderIds[0]];
    const overlay = overlayFor(first);
    expect(Object.fromEntries(overlay.boxes.map((b) => [b.id, b.status]))).toEqual({
      logo: 'fail', headline: 'pass', subhead: 'fail', features: null, product: 'pass', badge: null, price: null, disclaimer: 'warn',
    });
    expect(overlay.boxes.find((b) => b.id === 'logo')!.issues).toEqual(['Logo 淨空區', '物件與文字遮擋']);
    expect(overlay.canvas).toEqual({ status: 'fail', issues: ['品牌主色色差'] });
  });
});

describe('retryDiffs', () => {
  it('shows what the rewrite changed and how the score moved', () => {
    const [diff] = retryDiffs(view);
    expect(diff).toMatchObject({ round: 1, templateId: 'ig-post', requery: true });
    expect(diff.diffs.map((d) => d.path)).toEqual([
      'palette.primary', 'palette.secondary', 'layout[logo].bbox', 'copy.subhead', 'copy.disclaimer', 'negativePrompt',
    ]);
    expect(diff.scoreBefore).toBeLessThan(50);
    expect(diff.scoreAfter).toBeGreaterThan(90);
  });

  it('has no diff before the next round is generated', () => {
    const [diff] = retryDiffs(upTo('rewrite.started'));
    expect(diff.diffs).toEqual([]);
    expect(diff.scoreAfter).toBeNull();
  });
});
