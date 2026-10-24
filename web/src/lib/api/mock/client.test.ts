import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobEvent, JobInput, JobMessage, ProductCutout } from '@/types/contract';
import { historyChunk } from '@/lib/rag/history';
import { chunkKind } from '@/lib/rag/kind';
import type { ApiClient, ProductDraft } from '../client';
import { getApiClient } from '../index';
import { MAX_STORED_JOBS, MockApiClient, makeJobId } from './client';
import { MISTY_ISLE } from './data';
import { MemoryStore } from './store';

const BRIEF = '週年慶主打買一送一，溫柔療癒';
const NOW = new Date(2026, 9, 5, 9, 30);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => vi.useRealTimers());

async function startJob(api: MockApiClient, over: Partial<JobInput> = {}) {
  const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
  const { jobId } = await api.createJob({
    brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
    variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2, visualStyleId: null,
    ...over,
  });
  const events: JobEvent[] = [];
  api.subscribe(jobId, (e) => events.push(e));
  return { jobId, events };
}

const statuses = (events: JobEvent[]) => events.flatMap((e) => (e.type === 'job.status' ? [e.stage] : []));

describe('makeJobId', () => {
  it('formats the local date, time and a 4-hex suffix', () => {
    expect(makeJobId(NOW, () => 0.5)).toBe('job_20261005_0930_7fff');
  });
});

describe('products', () => {
  it('lists samples per brand, saves and deletes custom products', async () => {
    const api = new MockApiClient();
    expect((await api.listProducts('selune')).map((p) => p.id)).toEqual(['prod_selune_serum']);
    const saved = await api.saveProduct({
      brandId: 'selune', name: '晚安面膜', features: ['保濕'], price: { sale: 680, original: 880 },
      photo: { source: 'upload', url: 'blob:test' }, cutout: null,
    });
    expect(saved.id).toMatch(/^prod_/);
    expect(saved.createdAt).toBe(NOW.toISOString());
    expect((await api.listProducts('selune')).map((p) => p.name)).toEqual(['極光玻尿酸修護精華 30ml', '晚安面膜']);
    await api.deleteProduct(saved.id);
    await api.deleteProduct('prod_selune_serum');
    expect(await api.listProducts('selune')).toEqual([]);
    expect(await api.listProducts('misty-isle')).toHaveLength(1);
  });
});

describe('product photos and cutout', () => {
  it('turns an uploaded image into a data URL photo', async () => {
    const api = new MockApiClient();
    const photo = await api.uploadProductPhoto(new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' }));
    expect(photo).toEqual({ source: 'upload', url: 'data:image/png;base64,AQID' });
    await expect(api.uploadProductPhoto(new Blob(['x'], { type: 'text/plain' }))).rejects.toThrow('只能上傳圖片檔');
  });

  const PENDING: ProductCutout = { model: 'BiRefNet-general', status: 'pending', url: null, error: null };
  const DONE: ProductCutout = { model: 'BiRefNet-general', status: 'done', url: null, error: null };
  const DRAFT: ProductDraft = {
    brandId: 'selune', name: '晚安面膜', features: [], price: { sale: 680, original: 880 },
    photo: { source: 'upload', url: 'data:image/png;base64,AQID' }, cutout: null,
  };
  const cutoutOf = async (api: MockApiClient, id: string) => (await api.listProducts('selune')).find((p) => p.id === id)?.cutout;

  it('simulates the cutout of a new photo product in the background, like the backend', async () => {
    const api = new MockApiClient();
    const saved = await api.saveProduct({ ...DRAFT, cutout: DONE });
    // 去背狀態由「伺服器」管理：送來的 cutout 一律忽略
    expect(saved.cutout).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(1_100);
    expect(await cutoutOf(api, saved.id)).toEqual(PENDING);
    await vi.advanceTimersByTimeAsync(100);
    expect(await cutoutOf(api, saved.id)).toEqual(DONE);
    // 只改名稱：沿用原本的去背結果
    const renamed = await api.saveProduct({ ...DRAFT, id: saved.id, name: '晚安修護面膜' });
    expect(renamed.cutout).toEqual(DONE);
    // 示範商品不需要去背
    const sample = (await api.listProducts('selune'))[0];
    expect((await api.saveProduct({ ...sample, name: '改名' })).cutout).toBeNull();
  });

  it('re-runs a cutout on request and finishes cutouts left pending by a reload', async () => {
    const store = new MemoryStore();
    const api = new MockApiClient(store);
    const saved = await api.saveProduct(DRAFT);
    await vi.advanceTimersByTimeAsync(1_200);
    const again = await api.requestCutout(saved.id);
    expect(again.cutout).toEqual(PENDING);
    expect(again.createdAt).toBe(saved.createdAt);
    await vi.advanceTimersByTimeAsync(1_200);
    expect(await cutoutOf(api, saved.id)).toEqual(DONE);
    await expect(api.requestCutout('prod_selune_serum')).rejects.toThrow('示範商品已是去背素材');
    // 重新整理頁面：排程不在了，下一次讀取時直接完成
    await api.requestCutout(saved.id);
    expect(await cutoutOf(new MockApiClient(store), saved.id)).toEqual(DONE);
  });
});

describe('brand documents', () => {
  const TEXT = ['# 色彩更新', '新增輔助色「霧粉」#E8C7C8。', '', '# Logo', '深色背景使用反白 Logo。'].join('\n');
  const file = (text = TEXT, name = 'ci_update.md', type = 'text/markdown') => new File([text], name, { type });

  it('reports chunking, embedding and storing, then lists the new chunks on the brand', async () => {
    const api = new MockApiClient();
    const seen: string[] = [];
    const pending = api.ingestBrandDocument('selune', file(), (e) => seen.push(e.type));
    await vi.advanceTimersByTimeAsync(1_300);
    const chunks = await pending;
    expect(seen).toEqual(['ingest.chunked', 'ingest.embedded', 'ingest.embedded', 'ingest.stored']);
    expect(chunks.map((c) => c.tag)).toEqual(['color', 'logo']);
    const selune = (await api.listBrands()).find((b) => b.id === 'selune')!;
    expect(selune.guidelineChunks.slice(-2).map((c) => c.id)).toEqual(chunks.map((c) => c.id));
    expect((await api.listBrands()).find((b) => b.id === 'misty-isle')!.guidelineChunks).toEqual(MISTY_ISLE.guidelineChunks);
  });

  it('replaces chunks when the same document is uploaded again', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const first = api.ingestBrandDocument('selune', file(), () => {});
    await vi.advanceTimersByTimeAsync(400);
    await first;
    const second = api.ingestBrandDocument('selune', file('只剩一段。'), () => {});
    await vi.advanceTimersByTimeAsync(400);
    await second;
    const selune = (await api.listBrands()).find((b) => b.id === 'selune')!;
    expect(selune.guidelineChunks.filter((c) => c.source === 'ci_update.md').map((c) => c.text)).toEqual(['只剩一段。']);
  });

  it('reads .markdown and .txt files whatever the case of the extension', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    for (const name of ['notes.markdown', 'NOTES.TXT']) {
      const pending = api.ingestBrandDocument('selune', file('主色維持 #B76E79。', name, 'text/plain'), () => {});
      await vi.advanceTimersByTimeAsync(300);
      expect((await pending).map((c) => [c.source, c.tag])).toEqual([[name, 'color']]);
    }
  });

  it('rejects PDFs and other formats, and documents without text', async () => {
    const api = new MockApiClient();
    const pdf = file('%PDF-1.7', 'ci.pdf', 'application/pdf');
    await expect(api.ingestBrandDocument('selune', pdf, () => {})).rejects.toThrow('示範模式只能讀取 .md、.txt');
    await expect(api.ingestBrandDocument('selune', file('x', 'ci.docx', ''), () => {})).rejects.toThrow('示範模式只能讀取 .md、.txt');
    await expect(api.ingestBrandDocument('selune', file('  ', 'a.txt'), () => {})).rejects.toThrow('文件沒有可用的文字內容');
    expect((await api.listBrands()).find((b) => b.id === 'selune')!.guidelineChunks.some((c) => c.id.includes('#doc-'))).toBe(false);
  });
});

describe('jobs', () => {
  it('runs the default demo to completion and replays events to late subscribers', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    expect(statuses(events).at(-1)).toBe('done');
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
    const late: JobEvent[] = [];
    api.subscribe(jobId, (e) => late.push(e));
    expect(late).toEqual(events);
  });

  it('stamps every event with a consecutive sequence number and the time it was sent', async () => {
    const api = new MockApiClient();
    const { jobId } = await startJob(api);
    const messages: JobMessage[] = [];
    api.subscribe(jobId, (m) => messages.push(m));
    await vi.advanceTimersByTimeAsync(14_500);
    expect(messages.map((m) => m.seq)).toEqual(messages.map((_, i) => i + 1));
    expect(messages[0].ts).toBe(NOW.toISOString());
    expect(Date.parse(messages.at(-1)!.ts) - NOW.getTime()).toBe(14_500);
    const times = messages.map((m) => Date.parse(m.ts));
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(Object.isFrozen(messages[0])).toBe(true);
  });

  it('respects the demo speed', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const { events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(3_700);
    expect(events.some((e) => e.type === 'job.completed')).toBe(true);
  });

  it('can be cancelled', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(1_000);
    await api.cancelJob(jobId);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.at(-1)).toMatchObject({ type: 'job.status', stage: 'cancelled', round: 0 });
    expect(events.some((e) => e.type === 'job.completed')).toBe(false);
  });

  it('saves the selected render with edited copy to history', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');

    const copy = { ...prompt.spec.copy, price: { ...prompt.spec.copy.price, sale: 999 } };
    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, copy);
    expect(entry).toMatchObject({ jobId, brandId: 'selune', templateId: 'ig-post', favorite: false, writtenToRag: true });
    expect(entry.render.passed).toBe(true);
    expect(entry.render.checks).toHaveLength(11);
    expect(entry.copy.price.sale).toBe(999);
    expect(entry.input.brief).toBe(BRIEF);
    expect(entry.input.templateIds).toEqual(['ig-post']);
    expect(await api.listHistory('selune')).toHaveLength(1);
    expect(await api.listHistory('misty-isle')).toHaveLength(0);
  });

  it('writes the selected render back as a history chunk listed after the uploaded documents', async () => {
    const store = new MemoryStore();
    const api = new MockApiClient(store);
    api.demo.set({ speed: 4 });
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');

    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    const uploading = api.ingestBrandDocument('selune', new File(['主色維持 #B76E79。'], 'later.md'), () => {});
    await vi.advanceTimersByTimeAsync(300);
    const [uploaded] = await uploading;
    const chunks = (await new MockApiClient(store).listBrands()).find((b) => b.id === 'selune')!.guidelineChunks;
    // 與後端相同：設定檔、上傳的手冊、歷史回寫
    expect(chunks.slice(-2)).toEqual([uploaded, historyChunk(entry, '極光玻尿酸修護精華 30ml')]);
    expect(chunkKind(chunks.at(-1)!.id)).toBe('history');
    expect(chunks.at(-1)).toMatchObject({ id: `selune#hist-${entry.id}`, source: `history/${jobId}`, tag: 'history' });
    expect((await api.listBrands()).find((b) => b.id === 'misty-isle')!.guidelineChunks).toEqual(MISTY_ISLE.guidelineChunks);
  });

  it('leaves the product name out of the history chunk when the product was deleted', async () => {
    const api = new MockApiClient();
    api.demo.set({ speed: 4 });
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated');
    if (prompt?.type !== 'prompt.generated') throw new Error('missing prompt');
    await api.deleteProduct('prod_selune_serum');

    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    const chunk = (await api.listBrands()).find((b) => b.id === 'selune')!.guidelineChunks.at(-1);
    expect(chunk).toEqual(historyChunk(entry, null));
    expect(chunk?.text).toMatch(/^IG 貼文海報，審查 \d+ 分。/);
  });

  it('rejects empty template lists', async () => {
    const api = new MockApiClient();
    await expect(startJob(api, { templateIds: [] })).rejects.toThrow('至少要選一個通路模板');
  });

  it('reports unknown jobs through onError instead of throwing', async () => {
    const api = new MockApiClient();
    const onError = vi.fn();
    api.subscribe('nope', () => {}, onError);
    expect(onError).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'Unknown job: nope' }));
  });

  it('keeps every history entry when selections run concurrently', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api, { templateIds: ['ig-post', 'story'] });
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    await Promise.all([
      api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy),
      api.selectRender(jobId, done.bestRenderIds.story!, prompt.spec.copy),
    ]);
    expect((await api.listHistory('selune')).map((h) => h.templateId).sort()).toEqual(['ig-post', 'story']);
  });

  it('keeps every product when saves run concurrently', async () => {
    const api = new MockApiClient();
    const draft = (name: string) => ({
      brandId: 'selune', name, features: [], price: { sale: 1, original: 1 }, photo: { source: 'upload' as const, url: 'blob:x' },
      cutout: null,
    });
    await Promise.all([api.saveProduct(draft('A')), api.saveProduct(draft('B'))]);
    expect((await api.listProducts('selune')).map((p) => p.name)).toEqual(['極光玻尿酸修護精華 30ml', 'A', 'B']);
  });

  it('keeps delivering to other subscribers when one throws', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const api = new MockApiClient();
      const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
      const { jobId } = await api.createJob({
        brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
        variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2, visualStyleId: null,
      });
      api.subscribe(jobId, () => { throw new Error('boom'); });
      const events: JobEvent[] = [];
      api.subscribe(jobId, (e) => events.push(e));
      await vi.advanceTimersByTimeAsync(14_500);
      expect(statuses(events).at(-1)).toBe('done');
      expect(error).toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });

  it('stops delivery immediately when a subscriber cancels inside a handler', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    api.subscribe(jobId, (e) => { if (e.type === 'job.accepted') void api.cancelJob(jobId); });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(events.map((e) => (e.type === 'job.status' ? e.stage : e.type))).toEqual(['job.accepted', 'cancelled']);
  });

  it('registers a subscriber even if it throws while replaying past events', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const api = new MockApiClient();
      const { jobId } = await startJob(api);
      await vi.advanceTimersByTimeAsync(1_000);
      const seen: string[] = [];
      api.subscribe(jobId, (e) => {
        if (e.type === 'job.accepted') throw new Error('replay boom');
        seen.push(e.type);
      });
      await vi.advanceTimersByTimeAsync(14_000);
      expect(seen).toContain('job.completed');
      expect(error).toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });

  it('rejects invalid job input', async () => {
    const api = new MockApiClient();
    await expect(startJob(api, { templateIds: ['ig-post', 'ig-post'] })).rejects.toThrow('通路模板不可重複');
    await expect(startJob(api, { variantsPerTemplate: 0 })).rejects.toThrow('每個模板的候選張數需為 1–8');
    await expect(startJob(api, { maxRetries: -1 })).rejects.toThrow('最大重試次數需為 0 以上的整數');
    await expect(startJob(api, { brandId: 'misty-isle' })).rejects.toThrow('商品不屬於所選品牌');
    await expect(startJob(api, { visualStyleId: 'nope' })).rejects.toThrow('品牌沒有這個背景風格：nope');
  });
});

describe('job queries, connection and favorites', () => {
  it('lists jobs newest first with their live status', async () => {
    const api = new MockApiClient();
    const first = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const second = await startJob(api, { templateIds: ['story'] });
    await vi.advanceTimersByTimeAsync(1_000);
    const jobs = await api.listJobs();
    expect(jobs.map((j) => j.id)).toEqual([second.jobId, first.jobId]);
    expect(jobs[1]).toMatchObject({ stage: 'done', round: 2, finished: true, createdAt: NOW.toISOString() });
    expect(jobs[1].bestRenderIds['ig-post']).toMatch(/_r2_ig-post_v\d$/);
    expect(jobs[0]).toMatchObject({ stage: 'parsing', finished: false, bestRenderIds: {} });
    expect(jobs[0].input.templateIds).toEqual(['story']);
  });

  it('returns a snapshot of a job and its events', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(5_000);
    const snap = await api.getJob(jobId);
    expect(snap.summary.id).toBe(jobId);
    expect(snap.events).toEqual(events);
    await expect(api.getJob('nope')).rejects.toThrow('Unknown job');
  });

  it('keeps the input it was given, even if the caller mutates it later', async () => {
    const api = new MockApiClient();
    const parsedBrief = await api.parseBrief('selune', BRIEF, 'prod_selune_serum');
    const input: JobInput = {
      brandId: 'selune', productId: 'prod_selune_serum', brief: BRIEF, parsedBrief, templateIds: ['ig-post'],
      variantsPerTemplate: 4, llm: 'Gemini 3.7 Flash', engine: 'comfyui', vlm: 'Gemini 3.7 Vision', maxRetries: 2, visualStyleId: null,
    };
    const { jobId } = await api.createJob(input);
    input.templateIds.push('story');
    expect((await api.getJob(jobId)).summary.input.templateIds).toEqual(['ig-post']);
  });

  it('is always connected in mock mode', () => {
    const api = new MockApiClient();
    expect(api.connection.get()).toEqual({ status: 'connected', transport: 'mock', error: null });
    expect(api.connection.get()).toBe(api.connection.get());
    const unsubscribe = api.connection.subscribe(() => {});
    expect(typeof unsubscribe).toBe('function');
  });

  it('toggles favorites on history entries', async () => {
    const api = new MockApiClient();
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    const entry = await api.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    expect((await api.setFavorite(entry.id, true)).favorite).toBe(true);
    expect((await api.listHistory('selune'))[0].favorite).toBe(true);
    await expect(api.setFavorite('nope', true)).rejects.toThrow('Unknown history entry');
  });
});

describe('stored jobs', () => {
  it('keeps finished and cancelled jobs so a reloaded client can list, replay and select from them', async () => {
    const store = new MemoryStore();
    const api = new MockApiClient(store);
    const { jobId, events } = await startJob(api);
    await vi.advanceTimersByTimeAsync(14_500);
    const cancelled = await startJob(api, { templateIds: ['story'] });
    await api.cancelJob(cancelled.jobId);

    const reloaded = new MockApiClient(store);
    const jobs = await reloaded.listJobs();
    expect(jobs.map((j) => j.id)).toEqual([cancelled.jobId, jobId]);
    expect(jobs[0]).toMatchObject({ stage: 'cancelled', finished: true });
    expect(jobs[1]).toMatchObject({ stage: 'done', round: 2, finished: true });
    expect((await reloaded.getJob(jobId)).events).toEqual(events);

    const replayed: JobMessage[] = [];
    reloaded.subscribe(jobId, (m) => replayed.push(m));
    await vi.waitFor(() => expect(replayed).toEqual(events));

    const done = events.find((e) => e.type === 'job.completed');
    if (done?.type !== 'job.completed') throw new Error('job did not complete');
    const prompt = events.find((e) => e.type === 'prompt.generated' && e.round === 2);
    if (prompt?.type !== 'prompt.generated') throw new Error('missing round 2 prompt');
    const entry = await reloaded.selectRender(jobId, done.bestRenderIds['ig-post']!, prompt.spec.copy);
    expect(entry.render).toMatchObject({ passed: true, round: 2 });
    expect(entry.render.checks).toHaveLength(11);
  });

  it('seeds finished sample jobs with 1× timestamps and keeps only the newest ones', async () => {
    const api = new MockApiClient();
    expect(await api.demo.seedJobs(6)).toBe(6);
    const jobs = await api.listJobs();
    expect(jobs).toHaveLength(6);
    expect(jobs.every((j) => j.finished)).toBe(true);
    expect(jobs.map((j) => j.stage).sort()).toEqual(['done', 'done', 'done', 'done', 'done', 'needs_review']);
    const created = jobs.map((j) => j.createdAt);
    expect(created).toEqual([...created].sort().reverse());

    // 「強制全部失敗」的那一筆：3 輪後需人工審核，1× 共 20.8 秒
    const failed = jobs.find((j) => j.stage === 'needs_review')!;
    const snap = await api.getJob(failed.id);
    expect(snap.summary.round).toBe(3);
    expect(snap.events[0].ts).toBe(failed.createdAt);
    expect(snap.events.map((m) => m.seq)).toEqual(snap.events.map((_, i) => i + 1));
    expect(Date.parse(snap.events.at(-1)!.ts) - Date.parse(snap.events[0].ts)).toBe(20_800);

    await api.demo.seedJobs(MAX_STORED_JOBS);
    expect(await api.listJobs()).toHaveLength(MAX_STORED_JOBS);
  });

  it('computes dashboard stats from finished jobs, per brand or overall', async () => {
    const api = new MockApiClient();
    expect((await api.getDashboardStats()).jobs).toBe(0);
    await api.demo.seedJobs(6);
    const { jobId } = await startJob(api);
    await vi.advanceTimersByTimeAsync(1_000);
    // 執行中的任務不列入
    expect((await api.getDashboardStats()).jobs).toBe(6);
    await vi.advanceTimersByTimeAsync(13_500);
    const all = await api.getDashboardStats();
    expect(all.jobs).toBe(7);
    expect(all.recent[0].jobId).toBe(jobId);
    expect(all.passRate).toBeCloseTo(6 / 7, 10);
    expect((await api.getDashboardStats('selune')).jobs).toBe(4);
    expect((await api.getDashboardStats('misty-isle')).jobs).toBe(3);
  });
});

describe('options, system status and local photos', () => {
  it('offers every model and engine of the demo', async () => {
    expect(await new MockApiClient().getOptions()).toEqual({
      llm: ['Gemini 3.7 Flash', 'Llama 3.2 Vision（Unsloth 微調）'],
      vlm: ['Gemini 3.7 Vision', 'Llama 3.2 Vision（Unsloth 微調）'],
      engines: ['comfyui', 'ideogram'],
    });
  });

  it('reports a single simulated component', async () => {
    expect(await new MockApiClient().getSystemStatus()).toEqual({
      components: [{ id: 'mock', label: '瀏覽器內模擬', status: 'sim', detail: 'MockApiClient：事件格式與 FastAPI WebSocket 相同' }],
    });
  });

  it('cannot read the local product folder', async () => {
    const api: ApiClient = new MockApiClient();
    expect(await api.listLocalPhotos()).toBeNull();
    await expect(api.importLocalPhoto('mask.png', 'selune')).rejects.toThrow('只有 live 模式可以匯入本機資料夾');
  });
});

describe('getApiClient', () => {
  it('returns a singleton mock client with demo controls by default', () => {
    const api = getApiClient();
    expect(api).toBe(getApiClient());
    expect(api.demo?.get()).toEqual({ speed: 1, firstRoundFail: true, forceAllFail: false });
  });
});
