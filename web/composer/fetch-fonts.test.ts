import { createHash } from 'node:crypto';
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_FONTS_DIR, fetchFonts, readFontLock, verifyFont } from '../scripts/fetch-fonts.mjs';

const body = (text: string) => Buffer.from(text, 'utf8');
const entry = (file: string, text: string) => ({
  file, url: `https://fonts.test/${file}`, bytes: body(text).length,
  sha256: createHash('sha256').update(body(text)).digest('hex'),
});
const FILES = [entry('A.ttf', 'font A'), entry('OFL.txt', 'licence')];

/** 假的 fetch：依網址回傳內容，記錄被呼叫的網址 */
function fakeFetch(contents: Record<string, string | number>) {
  const calls: string[] = [];
  const impl = async (url: string | URL | Request) => {
    const key = String(url);
    calls.push(key);
    const v = contents[key];
    return typeof v === 'number' ? new Response('nope', { status: v }) : new Response(body(v));
  };
  return { calls, impl: impl as typeof fetch };
}
const good = () => fakeFetch(Object.fromEntries(FILES.map((f) => [f.url, f.file === 'A.ttf' ? 'font A' : 'licence'])));

let dir = '';
beforeEach(() => {
  dir = path.join(mkdtempSync(path.join(tmpdir(), 'fetch-fonts-')), 'fonts');
});
afterEach(() => rmSync(path.dirname(dir), { recursive: true, force: true }));

describe('fetchFonts', () => {
  it('downloads every file, verifies it and skips verified files on the next run', async () => {
    const first = good();
    expect(await fetchFonts({ dir, files: FILES, fetchImpl: first.impl, log: () => {} })).toEqual({
      downloaded: ['A.ttf', 'OFL.txt'], skipped: [],
    });
    expect(readFileSync(path.join(dir, 'A.ttf'), 'utf8')).toBe('font A');
    expect(readdirSync(dir).sort()).toEqual(['A.ttf', 'OFL.txt']);

    const second = good();
    expect(await fetchFonts({ dir, files: FILES, fetchImpl: second.impl, log: () => {} })).toEqual({
      downloaded: [], skipped: ['A.ttf', 'OFL.txt'],
    });
    expect(second.calls).toEqual([]);
  });

  it('re-downloads a local file that no longer matches the lock', async () => {
    await fetchFonts({ dir, files: FILES, fetchImpl: good().impl, log: () => {} });
    writeFileSync(path.join(dir, 'A.ttf'), 'font B');
    const again = good();
    const lines: string[] = [];
    expect((await fetchFonts({ dir, files: FILES, fetchImpl: again.impl, log: (l) => lines.push(l) })).downloaded).toEqual(['A.ttf']);
    expect(again.calls).toEqual(['https://fonts.test/A.ttf']);
    expect(lines).toEqual(['檔案與清單不符，重新下載：A.ttf（6 B）', '已存在，略過：OFL.txt']);
    expect(readFileSync(path.join(dir, 'A.ttf'), 'utf8')).toBe('font A');
  });

  it('rejects a download whose checksum differs and leaves nothing behind', async () => {
    const tampered = fakeFetch({ [FILES[0].url]: 'font X', [FILES[1].url]: 'licence' });
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: tampered.impl, log: () => {} }))
      .rejects.toThrow(`A.ttf 的 SHA-256 不符：預期 ${FILES[0].sha256}`);
    expect(readdirSync(dir)).toEqual([]);
  });

  it('reports HTTP and network errors in Chinese', async () => {
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: fakeFetch({ [FILES[0].url]: 404 }).impl, log: () => {} }))
      .rejects.toThrow('無法下載 A.ttf：HTTP 404（https://fonts.test/A.ttf）');
    const offline = (async () => {
      throw new TypeError('fetch failed');
    }) as typeof fetch;
    await expect(fetchFonts({ dir, files: FILES, fetchImpl: offline, log: () => {} }))
      .rejects.toThrow('無法下載 A.ttf：fetch failed（請確認可以連到 raw.githubusercontent.com）');
  });
});

describe('verifyFont', () => {
  it('checks the byte count before the checksum', () => {
    expect(() => verifyFont(FILES[0], body('font'))).toThrow('A.ttf 大小不符：預期 6 位元組，實際 4 位元組');
    expect(() => verifyFont(FILES[0], body('font A'))).not.toThrow();
  });
});

describe('the real lock file', () => {
  it('is read from composer/fonts.lock.json and downloads into composer/fonts by default', async () => {
    expect((await readFontLock()).map((f: { file: string }) => f.file)).toContain('NotoSansTC-VF.ttf');
    expect(DEFAULT_FONTS_DIR).toBe(path.join(path.dirname(fileURLToPath(import.meta.url)), 'fonts'));
  });
});
