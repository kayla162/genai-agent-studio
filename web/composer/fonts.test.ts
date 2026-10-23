import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createCanvas, GlobalFonts } from '@napi-rs/canvas';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { SELUNE } from '@/lib/api/mock/data';
import { fontStacks } from '@/lib/compose/assets';
import lock from './fonts.lock.json';
import { FONTS_HINT, missingPosterFonts, POSTER_FONTS, registerPosterFonts, resolveFontsDir } from './fonts';

const FONTS_DIR = resolveFontsDir();
const MISSING = missingPosterFonts(FONTS_DIR);
if (MISSING.length) console.warn(`略過需要字型的測試：找不到 ${MISSING.join('、')}。${FONTS_HINT}`);

const PINNED = 'https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/';

describe('fonts.lock.json', () => {
  it('pins both poster fonts and their licences to one google/fonts commit', () => {
    expect(lock.files.map((f) => f.file)).toEqual([
      'NotoSansTC-VF.ttf', 'NotoSerifTC-VF.ttf', 'OFL-NotoSansTC.txt', 'OFL-NotoSerifTC.txt',
    ]);
    for (const f of POSTER_FONTS) expect(lock.files.map((e) => e.file)).toContain(f.file);
    for (const f of lock.files) {
      expect(f.url.startsWith(PINNED)).toBe(true);
      expect(f.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(f.bytes).toBeGreaterThan(0);
    }
  });
});

describe('resolveFontsDir', () => {
  it('defaults to web/composer/fonts and honours POSTER_FONTS_DIR', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    expect(resolveFontsDir({})).toBe(path.join(here, 'fonts'));
    expect(resolveFontsDir({ POSTER_FONTS_DIR: 'some/fonts' })).toBe(path.resolve('some/fonts'));
  });
});

describe('registerPosterFonts failures', () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'poster-fonts-'));
  afterAll(() => rmSync(tmp, { recursive: true, force: true }));

  it('names the missing files, points at npm run fonts and keeps the current fonts', () => {
    const before = GlobalFonts.families.length;
    expect(() => registerPosterFonts(tmp)).toThrow(/找不到字型檔：.*NotoSansTC-VF\.ttf.*NotoSerifTC-VF\.ttf.*npm run fonts/);
    expect(GlobalFonts.families.length).toBe(before);
  });

  it('throws when a font file cannot be registered', () => {
    for (const f of POSTER_FONTS) writeFileSync(path.join(tmp, f.file), 'not a font');
    expect(() => registerPosterFonts(tmp)).toThrow(/字型註冊失敗：.*NotoSansTC-VF\.ttf（Noto Sans TC）/);
  });
});

describe.skipIf(MISSING.length > 0)(`registerPosterFonts with the pinned fonts（沒有字型時略過：${FONTS_HINT}）`, () => {
  const ctx = createCanvas(16, 16).getContext('2d');
  const stacks = fontStacks(SELUNE);
  const width = (font: string, text: string) => {
    ctx.font = font;
    return ctx.measureText(text).width;
  };

  beforeAll(() => {
    expect(registerPosterFonts(FONTS_DIR)).toEqual(
      POSTER_FONTS.map((f) => ({ family: f.family, path: path.join(FONTS_DIR, f.file) })),
    );
  });

  it('replaces every other font, including system fonts, with the two poster fonts', () => {
    expect(GlobalFonts.families.map((f) => f.family).sort()).toEqual(['Noto Sans TC', 'Noto Serif TC']);
    expect(GlobalFonts.has('Noto Sans TC')).toBe(true);
    expect(GlobalFonts.has('Noto Serif TC')).toBe(true);
  });

  it('gives CJK text one em per character at every weight the posters use', () => {
    const text = '溫柔呵護每一天';
    for (const w of [400, 500, 700]) expect(width(`${w} 100px ${stacks.body}`, text)).toBeCloseTo(700, 1);
    for (const w of [700, 900]) expect(width(`${w} 100px ${stacks.headline}`, text)).toBeCloseTo(700, 1);
  });

  it('drives the variable weight axis through ctx.font (Latin widths grow with weight)', () => {
    // 寬度在 Windows 與 Alpine 相同；系統內建的另一版 Noto Sans TC 量起來是 805，這裡量到的一定是我們的字型
    const text = 'Hamburgefonstiv 123';
    expect(width(`400 100px ${stacks.body}`, text)).toBeCloseTo(994.25, 0);
    expect(width(`500 100px ${stacks.body}`, text)).toBeCloseTo(1020.42, 0);
    expect(width(`700 100px ${stacks.body}`, text)).toBeCloseTo(1054.21, 0);
    expect(width(`700 100px ${stacks.headline}`, text)).toBeCloseTo(1082.73, 0);
    expect(width(`900 100px ${stacks.headline}`, text)).toBeCloseTo(1105.9, 0);
  });
});
