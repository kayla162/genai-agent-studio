// 產生海報字型的涵蓋表 src/lib/compose/glyphs.json：npm run glyphs（字型要先以 npm run fonts 下載）。
// 字型以 SHA-256 固定（composer/fonts.lock.json），所以這份表不會變；換字型版本時重新產生。
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readCmap } from '../composer/cmap';
import { FONTS_HINT, missingPosterFonts, POSTER_FONTS, resolveFontsDir } from '../composer/fonts';

/** 多個字型都涵蓋的字元，壓縮成 [開始, 結束] 區段 */
export function coverageRanges(fonts: Buffer[]): [number, number][] {
  const [first, ...rest] = fonts.map(readCmap);
  const common = [...first].filter((c) => rest.every((set) => set.has(c))).sort((a, b) => a - b);
  const ranges: [number, number][] = [];
  for (const c of common) {
    const last = ranges.at(-1);
    if (last && c === last[1] + 1) last[1] = c;
    else ranges.push([c, c]);
  }
  return ranges;
}

function main() {
  const dir = resolveFontsDir();
  const missing = missingPosterFonts(dir);
  if (missing.length) throw new Error(`找不到字型檔：${missing.join('、')}。${FONTS_HINT}`);
  const files = POSTER_FONTS.map((f) => ({ file: f.file, data: readFileSync(path.join(dir, f.file)) }));
  const ranges = coverageRanges(files.map((f) => f.data));
  const fonts = files.map((f) => ({ file: f.file, sha256: createHash('sha256').update(f.data).digest('hex') }));
  const target = fileURLToPath(new URL('../src/lib/compose/glyphs.json', import.meta.url));
  writeFileSync(target, `${JSON.stringify({ fonts, ranges })}\n`);
  const count = ranges.reduce((n, [start, end]) => n + end - start + 1, 0);
  console.log(`wrote src/lib/compose/glyphs.json：${count} 個字元、${ranges.length} 個區段`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
