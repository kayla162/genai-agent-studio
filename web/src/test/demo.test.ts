import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/** 作品集 Demo（Cloudflare Workers）的標頭與 robots：靜態輸出時從 public/ 複製到 out/（Plan 8） */
const PUBLIC = join(process.cwd(), 'public');
const read = (name: string) => readFileSync(join(PUBLIC, name), 'utf8');

describe('portfolio demo files', () => {
  it('sends the privacy and security headers on every path', () => {
    const lines = read('_headers').split(/\r?\n/).map((l) => l.trim());
    expect(lines[0]).toBe('/*');
    for (const header of [
      'X-Robots-Tag: noindex, nofollow',
      'X-Frame-Options: DENY',
      'X-Content-Type-Options: nosniff',
      'Referrer-Policy: strict-origin-when-cross-origin',
      'Permissions-Policy: camera=(), microphone=(), geolocation=()',
    ]) {
      expect(lines).toContain(header);
    }
  });

  it('keeps search engines out', () => {
    expect(read('robots.txt').split(/\r?\n/).filter(Boolean)).toEqual(['User-agent: *', 'Disallow: /']);
  });

  it('does not ship the create-next-app sample images', () => {
    for (const name of ['file.svg', 'globe.svg', 'next.svg', 'vercel.svg', 'window.svg']) {
      expect(existsSync(join(PUBLIC, name))).toBe(false);
    }
  });
});
