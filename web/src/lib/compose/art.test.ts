import { describe, it, expect } from 'vitest';
import { MISTY_ISLE, SELUNE } from '@/lib/api/mock/data';
import { backgroundSvg, bottleLabel, esc, productArtSvg, shade, svgDataUrl, type BackgroundOptions } from './art';

const opts = (over: Partial<BackgroundOptions> = {}): BackgroundOptions => ({
  width: 1440, height: 1800, palette: SELUNE.palette, seed: 42, style: 'selune', focus: { x: 634, y: 720, w: 720, h: 918 }, ...over,
});

describe('backgroundSvg', () => {
  it('is a standalone SVG sized to the template', () => {
    const svg = backgroundSvg(opts());
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1800" viewBox="0 0 1440 1800">')).toBe(true);
    expect(svg.endsWith('</svg>')).toBe(true);
    expect(svg).toContain(SELUNE.palette.secondary);
  });

  it('is deterministic per seed and differs between seeds and styles', () => {
    expect(backgroundSvg(opts())).toBe(backgroundSvg(opts()));
    expect(backgroundSvg(opts({ seed: 43 }))).not.toBe(backgroundSvg(opts()));
    const misty = backgroundSvg(opts({ style: 'misty-isle', palette: MISTY_ISLE.palette }));
    expect(misty).toContain('id="mist"');
    expect(backgroundSvg(opts({ style: 'unknown' }))).not.toBe(backgroundSvg(opts()));
  });

  it('contains no text and no external references', () => {
    for (const style of ['selune', 'misty-isle', 'unknown']) {
      const svg = backgroundSvg(opts({ style }));
      expect(svg).not.toContain('<text');
      expect(svg).not.toMatch(/href=|<image/);
    }
  });
});

describe('productArtSvg', () => {
  it('draws the serum and cold brew bottles with the product name on the label', () => {
    const serum = productArtSvg('serum', SELUNE.palette, '極光玻尿酸修護精華 30ml', 'SÉLUNE');
    expect(serum).toContain('viewBox="0 0 500 800"');
    expect(serum).toContain('極光玻尿酸');
    expect(serum).toContain('30 ml');
    const brew = productArtSvg('coldbrew', MISTY_ISLE.palette, '單一產區冷萃咖啡 330ml', 'MISTY ISLE');
    expect(brew).toContain('MISTY ISLE');
    expect(brew).toContain('clipPath');
  });

  it('escapes user-provided names', () => {
    const svg = productArtSvg('serum', SELUNE.palette, '<新>&', 'A&B');
    expect(svg).toContain('&lt;新&gt;&amp;');
    expect(svg).toContain('A&amp;B');
  });
});

describe('helpers', () => {
  it('bottleLabel splits long names and extracts the size', () => {
    expect(bottleLabel('極光玻尿酸修護精華 30ml')).toEqual({ lines: ['極光玻尿酸', '修護精華'], size: '30 ml' });
    expect(bottleLabel('冷萃 330ML')).toEqual({ lines: ['冷萃'], size: '330 ml' });
    expect(bottleLabel('晚安面膜')).toEqual({ lines: ['晚安面膜'], size: '' });
  });

  it('esc, shade and svgDataUrl', () => {
    expect(esc('"a" & <b>')).toBe('&quot;a&quot; &amp; &lt;b&gt;');
    expect(shade('#808080', 1)).toBe('#ffffff');
    expect(shade('#808080', -1)).toBe('#000000');
    expect(svgDataUrl('<svg/>')).toBe('data:image/svg+xml;charset=utf-8,%3Csvg%2F%3E');
  });
});
