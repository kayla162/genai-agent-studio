import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createComposerServer } from './app';

const server = createComposerServer();
let base = '';

beforeAll(async () => {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

const post = (path: string, body: string) =>
  fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });

describe('composer server', () => {
  it('answers health checks', async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok' });
  });

  it('runs a handler on POSTed JSON', async () => {
    const res = await post('/layout', JSON.stringify({ templateId: 'ig-post' }));
    expect(res.status).toBe(200);
    expect(await res.json()).toHaveLength(8);
  });

  it('reports bad requests as JSON errors', async () => {
    const unknown = await post('/nope', '{}');
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ error: { code: 'not_found', message: 'Unknown route: /nope' } });
    const broken = await post('/layout', '{');
    expect(broken.status).toBe(400);
    expect((await broken.json()).error.code).toBe('invalid');
  });
});
