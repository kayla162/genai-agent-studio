import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { FONTS_HINT, missingPosterFonts, POSTER_FONTS, resolveFontsDir } from '../../../composer/fonts';
import { coverageRanges } from '../../../scripts/glyphs';
import table from './glyphs.json';
import { GLYPH_RANGES, hasGlyph, missingGlyphs, stripEmoji } from './glyphs';

const FONTS_DIR = resolveFontsDir();
const HAS_FONTS = missingPosterFonts(FONTS_DIR).length === 0;
if (!HAS_FONTS) console.warn(`略過字型涵蓋表與字型檔的比對。${FONTS_HINT}`);

describe('stripEmoji', () => {
  it('removes emoji, joiners, keycaps, skin tones and flags', () => {
    expect(stripEmoji('醒來✨透亮💧')).toBe('醒來透亮');
    expect(stripEmoji('1️⃣ 第一')).toBe('1 第一');
    expect(stripEmoji('👩‍👩‍👧家庭')).toBe('家庭');
    expect(stripEmoji('🇹🇼台灣')).toBe('台灣');
    expect(stripEmoji('👍🏽讚')).toBe('讚');
    expect(stripEmoji('熬夜 🌙 也不怕')).toBe('熬夜 也不怕');
  });

  it('keeps ordinary text, digits, punctuation and the claim marker', () => {
    for (const text of ['7天感受透亮光采・專業修護配方*', 'LIMITED OFFER 2026', '買一送一！（限量）', '#1 好評']) {
      expect(stripEmoji(text)).toBe(text);
    }
  });
});

describe('missingGlyphs', () => {
  it('returns nothing for Traditional Chinese, Latin text and spaces', () => {
    expect(missingGlyphs('一夜溫柔修護 醒來透亮發光 NT$1,280 ★')).toEqual([]);
  });

  it('lists characters outside the table once, in order', () => {
    expect(missingGlyphs('这个这样们')).toEqual(['这', '们']);
    expect(missingGlyphs('晞月😀𠀀')).toEqual(['😀', '𠀀']);
  });

  it('looks characters up in sorted, non-overlapping ranges', () => {
    for (let i = 1; i < GLYPH_RANGES.length; i++) expect(GLYPH_RANGES[i][0]).toBeGreaterThan(GLYPH_RANGES[i - 1][1] + 1);
    const [start, end] = GLYPH_RANGES[GLYPH_RANGES.length >> 1];
    expect([hasGlyph(start), hasGlyph(end), hasGlyph(end + 1)]).toEqual([true, true, false]);
  });
});

describe.skipIf(!HAS_FONTS)('glyphs.json', () => {
  it('matches the pinned poster font files', () => {
    const files = POSTER_FONTS.map((f) => readFileSync(path.join(FONTS_DIR, f.file)));
    expect(table.fonts).toEqual(POSTER_FONTS.map((f, i) => ({
      file: f.file, sha256: createHash('sha256').update(files[i]).digest('hex'),
    })));
    expect(GLYPH_RANGES).toEqual(coverageRanges(files));
  });
});
