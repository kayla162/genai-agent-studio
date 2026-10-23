// 讀 TrueType／OpenType 字型的 cmap 表：字型實際涵蓋哪些字元（字型涵蓋表 glyphs.json 由此產生）。

/** 依序嘗試的 cmap 子表（platformID, encodingID）：完整 Unicode 優先，再來是 BMP */
const PREFERRED: [number, number][] = [[3, 10], [0, 6], [0, 4], [3, 1], [0, 3]];

function tableOffset(font: Buffer, tag: string): number | null {
  const numTables = font.readUInt16BE(4);
  for (let i = 0; i < numTables; i++) {
    const record = 12 + i * 16;
    if (font.toString('latin1', record, record + 4) === tag) return font.readUInt32BE(record + 8);
  }
  return null;
}

/** format 4（BMP）：每個區段以 idDelta 或 idRangeOffset 對應到字形；字形 0（.notdef）代表沒有這個字 */
function readFormat4(font: Buffer, at: number, out: Set<number>): void {
  const segCount = font.readUInt16BE(at + 6) / 2;
  const endCodes = at + 14;
  const startCodes = endCodes + segCount * 2 + 2;
  const idDeltas = startCodes + segCount * 2;
  const idRangeOffsets = idDeltas + segCount * 2;
  for (let s = 0; s < segCount; s++) {
    const end = font.readUInt16BE(endCodes + s * 2);
    const start = font.readUInt16BE(startCodes + s * 2);
    const delta = font.readInt16BE(idDeltas + s * 2);
    const rangeOffsetAt = idRangeOffsets + s * 2;
    const rangeOffset = font.readUInt16BE(rangeOffsetAt);
    for (let c = start; c <= end && c !== 0xffff; c++) {
      let glyph: number;
      if (rangeOffset === 0) glyph = (c + delta) & 0xffff;
      else {
        glyph = font.readUInt16BE(rangeOffsetAt + rangeOffset + (c - start) * 2);
        if (glyph !== 0) glyph = (glyph + delta) & 0xffff;
      }
      if (glyph !== 0) out.add(c);
    }
  }
}

/** format 12（完整 Unicode）：連續的字元對應到連續的字形 */
function readFormat12(font: Buffer, at: number, out: Set<number>): void {
  const groups = font.readUInt32BE(at + 12);
  for (let g = 0; g < groups; g++) {
    const record = at + 16 + g * 12;
    const start = font.readUInt32BE(record);
    const end = font.readUInt32BE(record + 4);
    const startGlyph = font.readUInt32BE(record + 8);
    for (let c = start; c <= end; c++) if (startGlyph + (c - start) !== 0) out.add(c);
  }
}

/** 字型涵蓋的字元（code point）。只支援 cmap format 4 與 12；找不到可用的子表時丟出中文錯誤 */
export function readCmap(font: Buffer): Set<number> {
  const cmap = tableOffset(font, 'cmap');
  if (cmap === null) throw new Error('字型沒有 cmap 表');
  const count = font.readUInt16BE(cmap + 2);
  const subtables = new Map<string, number>();
  for (let i = 0; i < count; i++) {
    const record = cmap + 4 + i * 8;
    const key = `${font.readUInt16BE(record)},${font.readUInt16BE(record + 2)}`;
    if (!subtables.has(key)) subtables.set(key, cmap + font.readUInt32BE(record + 4));
  }
  for (const [platform, encoding] of PREFERRED) {
    const at = subtables.get(`${platform},${encoding}`);
    if (at === undefined) continue;
    const format = font.readUInt16BE(at);
    const out = new Set<number>();
    if (format === 4) readFormat4(font, at, out);
    else if (format === 12) readFormat12(font, at, out);
    else continue;
    return out;
  }
  throw new Error('字型的 cmap 沒有支援的 Unicode 子表（format 4 或 12）');
}
