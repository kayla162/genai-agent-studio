import type { Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ReviewCheck } from '@/types/contract';
import { SELUNE } from '@/lib/api/mock/data';
import { cleanSpec } from '@/test/fixtures';
import { createComposerServer, MAX_BODY_BYTES } from './app';
import { BinaryResponse } from './handlers';

/** 在隨機埠啟動伺服器，回傳網址與關閉函式 */
async function start(server: Server): Promise<{ base: string; close: () => Promise<void> }> {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    base: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

const post = (base: string, path: string, body: string) =>
  fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });

/** 長度剛好 bytes 的 /layout 請求本文（以 pad 欄位補足） */
const layoutBody = (bytes: number) => {
  const head = '{"templateId":"ig-post","pad":"';
  return `${head}${'x'.repeat(bytes - head.length - 2)}"}`;
};

describe('composer server', () => {
  let base = '';
  let close: () => Promise<void>;
  beforeAll(async () => ({ base, close } = await start(createComposerServer({ fonts: ['Noto Sans TC', 'Noto Serif TC'] }))));
  afterAll(() => close());

  it('answers health checks with the registered poster fonts', async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok', fonts: ['Noto Sans TC', 'Noto Serif TC'] });
  });

  it('runs a handler on POSTed JSON', async () => {
    const res = await post(base, '/layout', JSON.stringify({ templateId: 'ig-post' }));
    expect(res.status).toBe(200);
    expect(await res.json()).toHaveLength(8);
  });

  it('reviews a spec with the measured primary', async () => {
    const res = await post(base, '/review', JSON.stringify({ spec: cleanSpec(), brand: SELUNE, measuredPrimary: '#b76e79' }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { checks: ReviewCheck[]; score: number; passed: boolean };
    expect(body.checks).toHaveLength(11);
    expect(body).toMatchObject({ score: 100, passed: true });
  });

  it('serves the guard and the glyph table as JSON', async () => {
    const glyphs = await post(base, '/glyphs', JSON.stringify({ texts: ['晞月', '这'] }));
    expect(glyphs.status).toBe(200);
    expect(await glyphs.json()).toEqual({ missing: [[], ['这']] });
    const spec = await post(base, '/spec', JSON.stringify({ draft: null, request: {} }));
    expect(spec.status).toBe(400);
    expect(await spec.json()).toEqual({ error: { code: 'invalid', message: 'draft 必須是物件' } });
  });

  it('reports bad requests as JSON errors', async () => {
    const unknown = await post(base, '/nope', '{}');
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ error: { code: 'not_found', message: 'Unknown route: /nope' } });
    const broken = await post(base, '/layout', '{');
    expect(broken.status).toBe(400);
    expect((await broken.json()).error.code).toBe('invalid');
    const review = await post(base, '/review', JSON.stringify({ spec: cleanSpec(), brand: SELUNE, measuredPrimary: 'pink' }));
    expect(review.status).toBe(400);
    expect((await review.json()).error).toEqual({ code: 'invalid', message: 'measuredPrimary 必須是 #RRGGBB 或 null："pink"' });
  });

  it(`accepts a body of exactly ${MAX_BODY_BYTES} bytes and rejects one byte more with a Chinese message`, async () => {
    const ok = await post(base, '/layout', layoutBody(MAX_BODY_BYTES));
    expect(ok.status).toBe(200);
    expect(await ok.json()).toHaveLength(8);
    const big = await post(base, '/layout', layoutBody(MAX_BODY_BYTES + 1));
    expect(big.status).toBe(400);
    expect(await big.json()).toEqual({ error: { code: 'too_large', message: '請求本文超過 30 MB 上限' } });
    // 超過上限後同一個伺服器照常服務
    expect((await post(base, '/layout', JSON.stringify({ templateId: 'story' }))).status).toBe(200);
  });
});

describe('composer server with async and binary handlers', () => {
  let base = '';
  let close: () => Promise<void>;
  beforeAll(async () => ({ base, close } = await start(createComposerServer({
    handle: async (path, body) => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      if (path === '/echo') return { echoed: body };
      if (path === '/bytes') return new BinaryResponse(Buffer.from([0, 1, 2, 255]), 'image/png', { 'X-Extra': 'yes', 'X-Empty': '' });
      throw new Error('非同步的 handler 失敗');
    },
  }))));
  afterAll(() => close());

  it('awaits async handlers before answering', async () => {
    const res = await post(base, '/echo', JSON.stringify({ a: 1 }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ echoed: { a: 1 } });
  });

  it('sends binary responses with their content type and custom headers', async () => {
    const res = await post(base, '/bytes', '{}');
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('image/png');
    expect(res.headers.get('content-length')).toBe('4');
    expect(res.headers.get('x-extra')).toBe('yes');
    expect(res.headers.get('x-empty')).toBe('');
    expect([...new Uint8Array(await res.arrayBuffer())]).toEqual([0, 1, 2, 255]);
  });

  it('turns rejected promises into JSON errors', async () => {
    const res = await post(base, '/fail', '{}');
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: { code: 'invalid', message: '非同步的 handler 失敗' } });
  });

  it('defaults /health to no fonts', async () => {
    expect(await (await fetch(`${base}/health`)).json()).toEqual({ status: 'ok', fonts: [] });
  });
});
