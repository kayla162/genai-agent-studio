import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, afterEach, describe, expect, it } from 'vitest';
import { FONTS_HINT, missingPosterFonts, resolveFontsDir } from './fonts';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MISSING = missingPosterFonts(resolveFontsDir());

const children: ChildProcess[] = [];
afterEach(() => {
  for (const child of children.splice(0)) child.kill();
});

/** 以 npm run composer 相同的方式啟動伺服器（隨機埠） */
function startComposer(env: Record<string, string>) {
  const child = spawn(process.execPath, ['--import', 'tsx', 'composer/server.ts'], {
    cwd: WEB, env: { ...process.env, PORT: '0', ...env }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.push(child);
  let stdout = '';
  let stderr = '';
  child.stdout!.on('data', (d: Buffer) => (stdout += d.toString('utf8')));
  child.stderr!.on('data', (d: Buffer) => (stderr += d.toString('utf8')));
  const exited = new Promise<number | null>((resolve) => child.once('exit', (code) => resolve(code)));
  const listening = new Promise<string>((resolve, reject) => {
    child.stdout!.on('data', () => {
      const url = /composer listening on (http:\/\/\S+?:\d+)/.exec(stdout)?.[1];
      if (url) resolve(url);
    });
    void exited.then((code) => reject(new Error(`composer 結束（代碼 ${code}）：${stderr}`)));
  });
  return { exited, listening, output: () => ({ stdout, stderr }) };
}

describe('composer server start-up', () => {
  const empty = mkdtempSync(path.join(tmpdir(), 'poster-fonts-empty-'));
  afterAll(() => rmSync(empty, { recursive: true, force: true }));

  it('exits with code 1 and the npm run fonts hint when the fonts are missing', async () => {
    const composer = startComposer({ POSTER_FONTS_DIR: empty });
    composer.listening.catch(() => undefined);
    expect(await composer.exited).toBe(1);
    const { stdout, stderr } = composer.output();
    expect(stdout).not.toContain('listening');
    expect(stderr).toContain('composer 無法啟動：找不到字型檔：');
    expect(stderr).toContain(FONTS_HINT);
  }, 30_000);

  it.skipIf(MISSING.length > 0)(`registers the fonts before listening and reports them on /health（沒有字型時略過：${FONTS_HINT}）`, async () => {
    const composer = startComposer({});
    const url = await composer.listening;
    expect(composer.output().stdout).toContain('字型：Noto Sans TC、Noto Serif TC');
    const health = await fetch(`${url}/health`);
    expect(await health.json()).toEqual({ status: 'ok', fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  }, 30_000);
});
