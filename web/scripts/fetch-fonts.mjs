// 下載 composer 伺服器端繪圖用的字型（Noto Sans／Serif TC 可變字重與 OFL 授權文字），核對位元組數與 SHA-256：
//   npm run fonts                 → 下載到 POSTER_FONTS_DIR，沒有設定時為 composer/fonts/（不進 git）
//   npm run fonts -- <資料夾>      → 下載到指定資料夾
// 清單在 composer/fonts.lock.json，Dockerfile 使用同一組網址與 SHA-256。已存在且核對無誤的檔案會略過，可重複執行。
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const WEB_DIR = path.resolve(import.meta.dirname, '..');
export const LOCK_PATH = path.join(WEB_DIR, 'composer', 'fonts.lock.json');
export const DEFAULT_FONTS_DIR = path.join(WEB_DIR, 'composer', 'fonts');

/** @typedef {{ file: string; url: string; bytes: number; sha256: string }} FontLockEntry */

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');
const size = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} KB` : `${n} B`);

/** 讀取字型清單（composer/fonts.lock.json） */
export async function readFontLock(lockPath = LOCK_PATH) {
  /** @type {{ files: FontLockEntry[] }} */
  const lock = JSON.parse(await readFile(lockPath, 'utf8'));
  return lock.files;
}

/**
 * 核對檔案內容與清單相符，不符時丟出中文錯誤。
 * @param {FontLockEntry} entry
 * @param {Buffer} buf
 */
export function verifyFont(entry, buf) {
  if (buf.length !== entry.bytes) {
    throw new Error(`${entry.file} 大小不符：預期 ${entry.bytes} 位元組，實際 ${buf.length} 位元組`);
  }
  const actual = sha256(buf);
  if (actual !== entry.sha256) throw new Error(`${entry.file} 的 SHA-256 不符：預期 ${entry.sha256}，實際 ${actual}`);
}

/** @returns {Promise<'valid' | 'invalid' | 'missing'>} */
async function localState(target, entry) {
  try {
    if (!(await stat(target)).isFile()) return 'invalid';
    verifyFont(entry, await readFile(target));
    return 'valid';
  } catch (err) {
    return err && err.code === 'ENOENT' ? 'missing' : 'invalid';
  }
}

/**
 * @param {FontLockEntry} entry
 * @param {typeof fetch} fetchImpl
 * @param {number} timeoutMs
 */
async function download(entry, fetchImpl, timeoutMs) {
  let res;
  let buf;
  try {
    res = await fetchImpl(entry.url, { signal: AbortSignal.timeout(timeoutMs) });
    if (res.ok) buf = Buffer.from(await res.arrayBuffer());
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`無法下載 ${entry.file}：${reason}（請確認可以連到 raw.githubusercontent.com）`, { cause: err });
  }
  if (!res.ok) throw new Error(`無法下載 ${entry.file}：HTTP ${res.status}（${entry.url}）`);
  return buf;
}

/**
 * 下載清單上的檔案到 dir 並逐一核對。先寫成 .part，核對通過才改名，中斷時不會留下不完整的字型檔。
 * @param {{ dir: string; files: FontLockEntry[]; fetchImpl?: typeof fetch; log?: (line: string) => void; timeoutMs?: number }} options
 * @returns {Promise<{ downloaded: string[]; skipped: string[] }>}
 */
export async function fetchFonts({ dir, files, fetchImpl = fetch, log = console.log, timeoutMs = 300_000 }) {
  await mkdir(dir, { recursive: true });
  const downloaded = [];
  const skipped = [];
  for (const entry of files) {
    const target = path.join(dir, entry.file);
    const state = await localState(target, entry);
    if (state === 'valid') {
      log(`已存在，略過：${entry.file}`);
      skipped.push(entry.file);
      continue;
    }
    log(`${state === 'invalid' ? '檔案與清單不符，重新下載' : '下載'}：${entry.file}（${size(entry.bytes)}）`);
    const buf = await download(entry, fetchImpl, timeoutMs);
    verifyFont(entry, buf);
    const part = `${target}.part`;
    try {
      await writeFile(part, buf);
      await rename(part, target);
    } catch (err) {
      await rm(part, { force: true });
      throw err;
    }
    downloaded.push(entry.file);
  }
  return { downloaded, skipped };
}

async function main() {
  const dir = path.resolve(process.argv[2] ?? process.env.POSTER_FONTS_DIR ?? DEFAULT_FONTS_DIR);
  try {
    const { downloaded, skipped } = await fetchFonts({ dir, files: await readFontLock() });
    console.log(`字型已就緒：${dir}（下載 ${downloaded.length} 個，已存在 ${skipped.length} 個）`);
  } catch (err) {
    console.error(`字型下載失敗：${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
