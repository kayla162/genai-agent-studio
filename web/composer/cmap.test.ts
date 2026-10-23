import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { coverageRanges } from '../scripts/glyphs';
import { readCmap } from './cmap';
import { FONTS_HINT, missingPosterFonts, resolveFontsDir } from './fonts';

const FONTS_DIR = resolveFontsDir();
const HAS_FONTS = missingPosterFonts(FONTS_DIR).length === 0;
if (!HAS_FONTS) console.warn(`略過需要字型的 cmap 測試。${FONTS_HINT}`);

interface Segment { start: number; end: number; delta?: number; glyphs?: number[] }

/** cmap format 4：區段以 idDelta 對應，或以 idRangeOffset 指到 glyphIdArray；最後一定是 0xFFFF 區段 */
function format4(segments: Segment[]): Buffer {
  const segs: Segment[] = [...segments, { start: 0xffff, end: 0xffff, delta: 1 }];
  const n = segs.length;
  const ends = 14;
  const starts = ends + n * 2 + 2;
  const deltas = starts + n * 2;
  const ranges = deltas + n * 2;
  const glyphWords = segs.reduce((k, s) => k + (s.glyphs?.length ?? 0), 0);
  const buf = Buffer.alloc(ranges + n * 2 + glyphWords * 2);
  buf.writeUInt16BE(4, 0);
  buf.writeUInt16BE(buf.length, 2);
  buf.writeUInt16BE(n * 2, 6);
  let glyphAt = ranges + n * 2;
  segs.forEach((s, i) => {
    buf.writeUInt16BE(s.end, ends + i * 2);
    buf.writeUInt16BE(s.start, starts + i * 2);
    buf.writeInt16BE(s.delta ?? 0, deltas + i * 2);
    if (!s.glyphs) return;
    buf.writeUInt16BE(glyphAt - (ranges + i * 2), ranges + i * 2);
    s.glyphs.forEach((g, j) => buf.writeUInt16BE(g, glyphAt + j * 2));
    glyphAt += s.glyphs.length * 2;
  });
  return buf;
}

/** cmap format 12：[開始, 結束, 第一個字形] */
function format12(groups: [number, number, number][]): Buffer {
  const buf = Buffer.alloc(16 + groups.length * 12);
  buf.writeUInt16BE(12, 0);
  buf.writeUInt32BE(buf.length, 4);
  buf.writeUInt32BE(groups.length, 12);
  groups.forEach(([start, end, glyph], i) => {
    buf.writeUInt32BE(start, 16 + i * 12);
    buf.writeUInt32BE(end, 20 + i * 12);
    buf.writeUInt32BE(glyph, 24 + i * 12);
  });
  return buf;
}

/** 只有一個表的最小字型檔（offset table ＋ 一筆 table record ＋ 表的內容） */
function font(tag: string, table: Buffer): Buffer {
  const head = Buffer.alloc(28);
  head.writeUInt32BE(0x00010000, 0);
  head.writeUInt16BE(1, 4);
  head.write(tag, 12, 'latin1');
  head.writeUInt32BE(28, 20);
  head.writeUInt32BE(table.length, 24);
  return Buffer.concat([head, table]);
}

function cmapFont(subtables: [platform: number, encoding: number, data: Buffer][]): Buffer {
  const header = Buffer.alloc(4 + subtables.length * 8);
  header.writeUInt16BE(subtables.length, 2);
  let offset = header.length;
  subtables.forEach(([platform, encoding, data], i) => {
    header.writeUInt16BE(platform, 4 + i * 8);
    header.writeUInt16BE(encoding, 6 + i * 8);
    header.writeUInt32BE(offset, 8 + i * 8);
    offset += data.length;
  });
  return font('cmap', Buffer.concat([header, ...subtables.map(([, , data]) => data)]));
}

const sorted = (set: Set<number>) => [...set].sort((a, b) => a - b);

describe('readCmap', () => {
  it('reads format 4 segments mapped by idDelta and by idRangeOffset', () => {
    const table = format4([
      { start: 0x30, end: 0x30, delta: -0x30 }, // 對到字形 0：沒有這個字
      { start: 0x41, end: 0x43, delta: -0x40 },
      { start: 0x6708, end: 0x670a, glyphs: [5, 0, 7] },
    ]);
    expect(sorted(readCmap(cmapFont([[3, 1, table]])))).toEqual([0x41, 0x42, 0x43, 0x6708, 0x670a]);
  });

  it('reads format 12 groups and skips characters mapped to .notdef', () => {
    const table = format12([[0x41, 0x43, 1], [0x1f600, 0x1f601, 0]]);
    expect(sorted(readCmap(cmapFont([[3, 10, table]])))).toEqual([0x41, 0x42, 0x43, 0x1f601]);
  });

  it('prefers the full Unicode subtable over the BMP one', () => {
    const bmp = format4([{ start: 0x41, end: 0x41, delta: -0x40 }]);
    const full = format12([[0x41, 0x42, 1], [0x20000, 0x20000, 3]]);
    expect(sorted(readCmap(cmapFont([[3, 1, bmp], [3, 10, full]])))).toEqual([0x41, 0x42, 0x20000]);
  });

  it('rejects fonts without a usable cmap', () => {
    expect(() => readCmap(font('head', Buffer.alloc(54)))).toThrow('字型沒有 cmap 表');
    expect(() => readCmap(cmapFont([[1, 0, format4([])]]))).toThrow('沒有支援的 Unicode 子表');
  });
});

describe('coverageRanges', () => {
  it('keeps the characters every font covers, as inclusive ranges', () => {
    const a = cmapFont([[3, 10, format12([[0x41, 0x45, 1], [0x6708, 0x670a, 9]])]]);
    const b = cmapFont([[3, 10, format12([[0x43, 0x48, 1], [0x670a, 0x670a, 2]])]]);
    expect(coverageRanges([a, b])).toEqual([[0x43, 0x45], [0x670a, 0x670a]]);
  });
});

describe.skipIf(!HAS_FONTS)('poster font cmap', () => {
  it('covers Traditional Chinese and Latin text but not emoji or Simplified-only characters', () => {
    const sans = readCmap(readFileSync(path.join(FONTS_DIR, 'NotoSansTC-VF.ttf')));
    for (const ch of '晞月透亮A1') expect(sans.has(ch.codePointAt(0)!)).toBe(true);
    for (const ch of ['😀', '这']) expect(sans.has(ch.codePointAt(0)!)).toBe(false);
  });
});
