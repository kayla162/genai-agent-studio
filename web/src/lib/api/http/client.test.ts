import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestEvent, Product } from '@/types/contract';
import type { ProductDraft } from '../client';
import { ApiError, HttpApiClient } from './client';

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

function setup(handler: Handler) {
  const fetch = vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => handler(String(url), init));
  const api = new HttpApiClient({ baseUrl: 'http://api.test', fetch: fetch as unknown as typeof globalThis.fetch });
  const call = (i: number) => {
    const [url, init = {}] = fetch.mock.calls[i];
    return { url: String(url), method: init.method, body: typeof init.body === 'string' ? JSON.parse(init.body) : init.body };
  };
  return { api, fetch, call };
}

const DRAFT: ProductDraft = {
  brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 590, original: 790 },
  photo: { source: 'upload', url: '/files/uploads/x.png' }, cutout: null,
};
const PRODUCT: Product = { ...DRAFT, id: 'prod_1', createdAt: '2026-10-08T01:00:00.000Z' };

/** 把 NDJSON 切成任意大小的片段送出（片段可能只有半行） */
function ndjson(lines: object[], size = 7): Response {
  const text = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
      controller.close();
    },
  });
  return new Response(body, { headers: { 'content-type': 'application/x-ndjson' } });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('HttpApiClient REST', () => {
  it('maps each method to its endpoint', async () => {
    const { api, call } = setup((url, init) => (init.method === 'DELETE' ? new Response(null, { status: 204 }) : Response.json(PRODUCT)));
    expect(await api.saveProduct(DRAFT)).toEqual(PRODUCT);
    await api.saveProduct({ ...DRAFT, id: 'prod_1' });
    await api.listProducts('selune');
    expect(await api.deleteProduct('prod_1')).toBeUndefined();
    await api.importLocalPhoto('精華液.png', 'selune');
    await api.listHistory();
    await api.getDashboardStats('misty-isle');
    await api.selectRender('job_1', 'r1', { headline: ['a', 'b'] } as never);
    expect([0, 1, 2, 3, 4, 5, 6, 7].map((i) => [call(i).method, call(i).url])).toEqual([
      ['POST', 'http://api.test/api/products'],
      ['PUT', 'http://api.test/api/products/prod_1'],
      ['GET', 'http://api.test/api/products?brandId=selune'],
      ['DELETE', 'http://api.test/api/products/prod_1'],
      ['POST', 'http://api.test/api/local-photos/%E7%B2%BE%E8%8F%AF%E6%B6%B2.png/import'],
      ['GET', 'http://api.test/api/history'],
      ['GET', 'http://api.test/api/stats?brandId=misty-isle'],
      ['POST', 'http://api.test/api/jobs/job_1/select'],
    ]);
    expect(call(0).body).toEqual(DRAFT);
    expect(call(4).body).toEqual({ brandId: 'selune' });
    expect(call(7).body).toEqual({ renderId: 'r1', copy: { headline: ['a', 'b'] } });
  });

  it('uploads product photos as multipart form data', async () => {
    const { api, call } = setup(() => Response.json({ source: 'upload', url: '/files/uploads/a.png' }, { status: 201 }));
    const photo = await api.uploadProductPhoto(new File([new Uint8Array([1, 2, 3])], 'serum.png', { type: 'image/png' }));
    expect(photo).toEqual({ source: 'upload', url: '/files/uploads/a.png' });
    const form = call(0).body as FormData;
    expect((form.get('file') as File).name).toBe('serum.png');
  });

  it('throws the server error message and tracks whether the backend is reachable', async () => {
    let reply: () => Response = () => Response.json({ error: { code: 'invalid', message: '至少要選一個通路模板' } }, { status: 400 });
    const { api } = setup(() => reply());
    const rejected = await api.createJob({} as never).catch((e: unknown) => e);
    expect(rejected).toBeInstanceOf(ApiError);
    expect(rejected).toMatchObject({ code: 'invalid', message: '至少要選一個通路模板', status: 400 });
    expect(api.connection.get().status).toBe('connected');

    reply = () => new Response('<html>Bad Gateway</html>', { status: 502 });
    await expect(api.listJobs()).rejects.toMatchObject({ code: 'http_error', message: '後端回應 HTTP 502' });
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '後端沒有回應（HTTP 502）' });

    reply = () => {
      throw new TypeError('fetch failed');
    };
    await expect(api.listJobs()).rejects.toMatchObject({ code: 'network', message: '無法連線到後端，請確認服務已啟動' });
    expect(api.connection.get()).toMatchObject({ status: 'disconnected', error: '無法連線到後端' });

    reply = () => Response.json([]);
    expect(await api.listJobs()).toEqual([]);
    expect(api.connection.get()).toMatchObject({ status: 'connected', error: null });
  });

  it('checks the backend while someone watches the connection, until it answers', async () => {
    let up = false;
    const { api, fetch } = setup(() => {
      if (!up) throw new TypeError('fetch failed');
      return Response.json({ status: 'ok' });
    });
    const states: string[] = [];
    api.connection.subscribe((s) => states.push(s.status));
    await vi.advanceTimersByTimeAsync(0);
    expect(states).toEqual(['disconnected']);
    await vi.advanceTimersByTimeAsync(1_000);
    up = true;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(states).toEqual(['disconnected', 'connected']);
    const probes = fetch.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch.mock.calls.length).toBe(probes);
    expect(fetch.mock.calls.every(([url]) => String(url) === 'http://api.test/api/health')).toBe(true);
  });
});

describe('HttpApiClient.ingestBrandDocument', () => {
  const chunk = { id: 'selune#doc-1', source: 'a.md', section: '色彩', tag: 'color' as const, text: '主色' };
  const progress: IngestEvent[] = [
    { type: 'ingest.chunked', source: 'a.md', chunks: [chunk] },
    { type: 'ingest.embedded', chunkId: chunk.id, index: 0, total: 1, dims: 1024, preview: [0.1, -0.2] },
    { type: 'ingest.stored', collection: 'selune_ci', count: 1 },
  ];

  it('reports each NDJSON line and returns the new chunks', async () => {
    const { api, call } = setup(() => ndjson(progress));
    const seen: IngestEvent[] = [];
    expect(await api.ingestBrandDocument('selune', { name: 'a.md', text: '# 色彩\n主色' }, (e) => seen.push(e))).toEqual([chunk]);
    expect(seen).toEqual(progress);
    expect([call(0).method, call(0).url, call(0).body]).toEqual([
      'POST', 'http://api.test/api/brands/selune/documents', { name: 'a.md', text: '# 色彩\n主色' },
    ]);
  });

  it('throws the error line, or when the stream ends early', async () => {
    let reply = () => ndjson([{ error: { code: 'invalid', message: '文件沒有可用的文字內容' } }]);
    const { api } = setup(() => reply());
    await expect(api.ingestBrandDocument('selune', { name: 'a.md', text: ' ' }, () => {})).rejects.toThrow('文件沒有可用的文字內容');
    reply = () => ndjson(progress.slice(0, 2));
    await expect(api.ingestBrandDocument('selune', { name: 'a.md', text: 'x' }, () => {})).rejects.toThrow('文件上傳的進度中斷');
  });
});
