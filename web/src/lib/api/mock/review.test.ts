import { describe, it, expect } from 'vitest';
import { CHANNEL_TEMPLATES } from '@/lib/compose/templates';
import { cleanSpec } from '@/test/fixtures';
import { SELUNE, MISTY_ISLE, SAMPLE_PRODUCTS } from './data';
import { applyFlaws, FLAWS } from './flaws';
import { reviewRender } from './review';

const coldbrew = SAMPLE_PRODUCTS.find((p) => p.id === 'prod_misty_coldbrew')!;
const status = (r: ReturnType<typeof reviewRender>, id: string) => r.checks.find((c) => c.id === id)?.status;

describe('reviewRender', () => {
  it('passes a clean spec with 10 checks and a high score', () => {
    const r = reviewRender(cleanSpec(), SELUNE, 0, 1);
    expect(r.checks).toHaveLength(10);
    expect(r.checks.filter((c) => c.kind === 'vlm')).toHaveLength(3);
    expect(r.passed).toBe(true);
    expect(r.score).toBeGreaterThanOrEqual(97);
  });

  it('adds VLM warnings for variants 1 and 2 but still passes', () => {
    const r1 = reviewRender(cleanSpec(), SELUNE, 1, 1);
    expect(status(r1, 'vlm_occlusion')).toBe('warn');
    expect(r1.passed).toBe(true);
    expect(r1.score).toBeLessThanOrEqual(94);
    expect(status(reviewRender(cleanSpec(), SELUNE, 2, 1), 'vlm_quality')).toBe('warn');
  });

  it('fails a fully flawed spec on both rules and VLM', () => {
    const r = reviewRender(applyFlaws(cleanSpec(), FLAWS, SELUNE), SELUNE, 0, 1);
    expect(r.passed).toBe(false);
    expect(r.checks.filter((c) => c.status === 'fail').map((c) => c.id)).toEqual([
      'banned_words', 'color_delta', 'logo_clearance', 'vlm_exaggeration', 'vlm_occlusion',
    ]);
    expect(status(r, 'disclaimer')).toBe('warn');
  });

  it.each(CHANNEL_TEMPLATES.map((t) => t.id))('passes clean cold brew specs for %s', (templateId) => {
    expect(reviewRender(cleanSpec(MISTY_ISLE, coldbrew, templateId), MISTY_ISLE, 0, 3).passed).toBe(true);
  });

  it('is deterministic for the same seed', () => {
    expect(reviewRender(cleanSpec(), SELUNE, 0, 9)).toEqual(reviewRender(cleanSpec(), SELUNE, 0, 9));
  });
});
