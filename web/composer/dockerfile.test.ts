// web/Dockerfile 的字型階段必須和 fonts.lock.json 一致：本機（npm run fonts）與 Docker 下載同一份檔案。
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import lock from './fonts.lock.json';

const DOCKERFILE = readFileSync(new URL('../Dockerfile', import.meta.url), 'utf8');

/** Dockerfile 的指令：合併以反斜線續行的行，去掉註解與空行 */
function instructions(text: string): string[] {
  return text
    .replace(/\\\r?\n/g, ' ')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => line.replace(/\s+/g, ' '));
}

/** 各階段（FROM … AS name）的指令 */
function stages(text: string): Map<string, string[]> {
  const result = new Map<string, string[]>();
  let current: string[] = [];
  for (const line of instructions(text)) {
    const from = /^FROM \S+ AS (\S+)$/i.exec(line);
    if (from) result.set(from[1], (current = []));
    else current.push(line);
  }
  return result;
}

const STAGES = stages(DOCKERFILE);
const FONTS_STAGE = STAGES.get('fonts') ?? [];
const COMPOSER_STAGE = STAGES.get('composer') ?? [];
const FONTS_DIR = '/usr/local/share/poster-fonts';

describe('web/Dockerfile fonts stage', () => {
  it('starts from scratch', () => {
    expect(DOCKERFILE).toMatch(/^FROM scratch AS fonts$/m);
  });

  it('downloads exactly the files in fonts.lock.json, with the same URLs and SHA-256', () => {
    const adds = FONTS_STAGE.map((line) => {
      const m = /^ADD --checksum=sha256:([0-9a-f]{64}) "([^"]+)" \/([^/\s]+)$/.exec(line);
      expect(m, `無法解析的指令：${line}`).not.toBeNull();
      const [, sha256, url, file] = m!;
      return { file, url, sha256 };
    });
    expect(adds).toEqual(lock.files.map(({ file, url, sha256 }) => ({ file, url, sha256 })));
  });
});

describe('web/Dockerfile composer stage', () => {
  it('creates the fonts dir, copies every locked file into it as 0644 and points POSTER_FONTS_DIR at it', () => {
    const mkdir = COMPOSER_STAGE.indexOf(`RUN mkdir -p ${FONTS_DIR}`);
    const copy = COMPOSER_STAGE.findIndex((line) => line.startsWith('COPY --chmod=0644 --from=fonts '));
    expect(mkdir).toBeGreaterThanOrEqual(0);
    expect(copy).toBeGreaterThan(mkdir);

    const [, , , ...args] = COMPOSER_STAGE[copy].split(' ');
    expect(args.at(-1)).toBe(`${FONTS_DIR}/`);
    expect(args.slice(0, -1)).toEqual(lock.files.map((f) => `/${f.file}`));
    expect(COMPOSER_STAGE).toContain(`ENV POSTER_FONTS_DIR=${FONTS_DIR}`);
  });
});
