import type {
  BrandDocument, ConnectionState, Copy, DemoOptions, HistoryEntry, IngestEvent, JobEvent, JobInput, JobMessage, JobStage,
  JobSummary, Product, ProductPhoto, RagChunk, Render, TemplateId,
} from '@/types/contract';
import type { ApiClient, ConnectionChannel, DemoControls, JobSnapshot, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { hashString } from '@/lib/core/num';
import { chunkDocument, EMBED_DIMS, embedPreview } from '@/lib/rag/chunk';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { playTimeline, type PlayerHandle } from './player';
import { sampleJobs } from './samples';
import { buildTimeline } from './scenario';
import { MemoryStore, type KeyValueStore } from './store';

interface JobRecord {
  id: string;
  input: JobInput;
  createdAt: string;
  events: JobMessage[];
  listeners: Set<(e: JobMessage) => void>;
  renders: Map<string, Render>;
  stage: JobStage;
  round: number;
  bestRenderIds: Partial<Record<TemplateId, string>>;
  finished: boolean;
  player: PlayerHandle | null;
}

/** mock 沒有真正的連線：永遠是「已連線」 */
const MOCK_CONNECTION: ConnectionState = Object.freeze({ status: 'connected', transport: 'mock', error: null });

const KEYS = {
  products: 'products', deleted: 'deletedSampleIds', history: 'history', docChunks: 'docChunks', jobs: 'jobs',
} as const;

/** 本機保留的已結束任務數（Agent 透視與成效儀表板使用），超過時刪掉最舊的 */
export const MAX_STORED_JOBS = 40;

function newRecord(id: string, input: JobInput, createdAt: string): JobRecord {
  return {
    id, input: structuredClone(input), createdAt, events: [], listeners: new Set(), renders: new Map(),
    stage: 'parsing', round: 0, bestRenderIds: {}, finished: false, player: null,
  };
}

/** 依事件更新任務狀態（任務列表與 selectRender 使用） */
function apply(rec: JobRecord, e: JobEvent) {
  switch (e.type) {
    case 'job.status':
      rec.stage = e.stage;
      rec.round = e.round;
      break;
    case 'job.completed':
      rec.bestRenderIds = { ...e.bestRenderIds };
      break;
    case 'render.completed':
      for (const r of e.renders) rec.renders.set(r.id, structuredClone(r));
      break;
    case 'review.check':
      rec.renders.get(e.renderId)?.checks.push(e.check);
      break;
    case 'review.completed': {
      const r = rec.renders.get(e.renderId);
      if (r) { r.score = e.score; r.passed = e.passed; }
      break;
    }
  }
}

/** 套用事件，加上序號與時間戳後保存；回傳凍結的訊息 */
function record(rec: JobRecord, e: JobEvent, ts: string): JobMessage {
  apply(rec, e);
  const message: JobMessage = Object.freeze({ ...e, seq: rec.events.length + 1, ts });
  rec.events.push(message);
  return message;
}

/** Blob → data URL（mock 把上傳的照片直接存在本機） */
async function toDataUrl(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:${file.type};base64,${btoa(binary)}`;
}
const pad = (n: number) => String(n).padStart(2, '0');

export function makeJobId(now: Date, rand: () => number = Math.random): string {
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `job_${date}_${time}_${Math.floor(rand() * 0xffff).toString(16).padStart(4, '0')}`;
}

const makeId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class MockApiClient implements ApiClient {
  readonly demo: DemoControls;
  readonly connection: ConnectionChannel = { get: () => MOCK_CONNECTION, subscribe: () => () => {} };
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
  private readonly jobs = new Map<string, JobRecord>();
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly store: KeyValueStore = new MemoryStore(),
    private readonly now: () => Date = () => new Date(),
  ) {
    this.demo = {
      get: () => ({ ...this.options }),
      set: (patch) => { this.options = { ...this.options, ...patch }; },
      seedJobs: (count) => this.seedJobs(count),
    };
  }

  /** 依序執行「讀取—修改—寫入」，避免並行呼叫互相覆蓋 */
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.tail.then(fn, fn);
    this.tail = run.catch(() => undefined);
    return run;
  }

  /** 等待 ms（1× 速度），依 Demo 播放速度縮短 */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms / this.options.speed));
  }

  /** 示範品牌 + 使用者上傳文件產生的切塊 */
  async listBrands() {
    const uploaded = (await this.store.get<Record<string, RagChunk[]>>(KEYS.docChunks)) ?? {};
    return BRANDS.map((b) => (uploaded[b.id]?.length ? { ...b, guidelineChunks: [...b.guidelineChunks, ...uploaded[b.id]] } : b));
  }

  async listTemplates() { return CHANNEL_TEMPLATES; }

  private async customProducts(): Promise<Product[]> {
    return (await this.store.get<Product[]>(KEYS.products)) ?? [];
  }

  async listProducts(brandId: string): Promise<Product[]> {
    const custom = await this.customProducts();
    const deleted = new Set((await this.store.get<string[]>(KEYS.deleted)) ?? []);
    const customIds = new Set(custom.map((p) => p.id));
    const samples = SAMPLE_PRODUCTS.filter((p) => !deleted.has(p.id) && !customIds.has(p.id));
    return [...samples, ...custom].filter((p) => p.brandId === brandId);
  }

  saveProduct(draft: ProductDraft): Promise<Product> {
    return this.serial(async () => {
      getBrandById(draft.brandId);
      const custom = await this.customProducts();
      const existing = draft.id
        ? (custom.find((p) => p.id === draft.id) ?? SAMPLE_PRODUCTS.find((p) => p.id === draft.id))
        : undefined;
      const product: Product = { ...draft, id: draft.id ?? makeId('prod'), createdAt: existing?.createdAt ?? this.now().toISOString() };
      await this.store.set(KEYS.products, [...custom.filter((p) => p.id !== product.id), product]);
      return product;
    });
  }

  deleteProduct(id: string): Promise<void> {
    return this.serial(async () => {
      const custom = await this.customProducts();
      await this.store.set(KEYS.products, custom.filter((p) => p.id !== id));
      if (SAMPLE_PRODUCTS.some((p) => p.id === id)) {
        const deleted = (await this.store.get<string[]>(KEYS.deleted)) ?? [];
        await this.store.set(KEYS.deleted, [...new Set([...deleted, id])]);
      }
    });
  }

  private async findProduct(id: string): Promise<Product> {
    const p = (await this.customProducts()).find((x) => x.id === id) ?? SAMPLE_PRODUCTS.find((x) => x.id === id);
    if (!p) throw new Error(`Unknown product: ${id}`);
    return p;
  }

  async uploadProductPhoto(file: Blob): Promise<ProductPhoto> {
    if (!file.type.startsWith('image/')) throw new Error('只能上傳圖片檔');
    return { source: 'upload', url: await toDataUrl(file) };
  }

  async requestCutout(productId: string): Promise<Product> {
    const product = await this.findProduct(productId);
    if (product.photo.source === 'sample') throw new Error('示範商品已是去背素材');
    await this.sleep(1200);
    return this.saveProduct({ ...product, cutout: { model: 'BiRefNet-general', url: null } });
  }

  async ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
    getBrandById(brandId);
    const chunks = chunkDocument(brandId, doc);
    if (!chunks.length) throw new Error('文件沒有可用的文字內容');
    await this.sleep(400);
    this.deliver(onEvent, { type: 'ingest.chunked', source: doc.name, chunks: structuredClone(chunks) });
    for (const [index, c] of chunks.entries()) {
      await this.sleep(250);
      this.deliver(onEvent, {
        type: 'ingest.embedded', chunkId: c.id, index, total: chunks.length, dims: EMBED_DIMS, preview: embedPreview(c.text),
      });
    }
    await this.serial(async () => {
      const all = (await this.store.get<Record<string, RagChunk[]>>(KEYS.docChunks)) ?? {};
      // 同名文件重新上傳時取代舊的切塊
      const kept = (all[brandId] ?? []).filter((c) => c.source !== doc.name);
      await this.store.set(KEYS.docChunks, { ...all, [brandId]: [...kept, ...chunks] });
    });
    await this.sleep(300);
    this.deliver(onEvent, { type: 'ingest.stored', collection: `${brandId}_ci`, count: chunks.length });
    return chunks;
  }

  async parseBrief(brandId: string, text: string, productId: string | null) {
    const brand = getBrandById(brandId);
    const product = productId ? await this.findProduct(productId) : null;
    return parseBrief(text, brand, product);
  }

  async createJob(input: JobInput): Promise<{ jobId: string }> {
    const brand = getBrandById(input.brandId);
    const product = await this.findProduct(input.productId);
    if (!input.templateIds.length) throw new Error('至少要選一個通路模板');
    if (new Set(input.templateIds).size !== input.templateIds.length) throw new Error('通路模板不可重複');
    if (!Number.isInteger(input.variantsPerTemplate) || input.variantsPerTemplate < 1 || input.variantsPerTemplate > 8) {
      throw new Error('每個模板的候選張數需為 1–8');
    }
    if (!Number.isInteger(input.maxRetries) || input.maxRetries < 0) throw new Error('最大重試次數需為 0 以上的整數');
    if (product.brandId !== brand.id) throw new Error('商品不屬於所選品牌');
    const templates = input.templateIds.map((id) => getTemplate(id));

    const now = this.now();
    const jobId = makeJobId(now);
    const rec = newRecord(jobId, input, now.toISOString());
    this.jobs.set(jobId, rec);

    const timeline = buildTimeline({ jobId, input, brand, product, templates, demo: this.demo.get(), seed: hashString(jobId) });
    rec.player = playTimeline(timeline, {
      getSpeed: () => this.options.speed,
      onEvent: (e) => this.dispatch(rec, e),
      onDone: () => {
        rec.finished = true;
        void this.persist(rec);
      },
    });
    return { jobId };
  }

  /** 示範任務：直接算出完整時間軸（時間戳以 1× 速度計），寫入已結束的任務紀錄 */
  private async seedJobs(count: number): Promise<number> {
    const snaps = sampleJobs(count, this.now()).map(({ input, demo, createdAt }) => {
      const brand = getBrandById(input.brandId);
      const product = SAMPLE_PRODUCTS.find((p) => p.id === input.productId);
      if (!product) throw new Error(`Unknown product: ${input.productId}`);
      const jobId = makeJobId(createdAt);
      const rec = newRecord(jobId, input, createdAt.toISOString());
      const templates = input.templateIds.map((id) => getTemplate(id));
      for (const { at, event } of buildTimeline({ jobId, input, brand, product, templates, demo, seed: hashString(jobId) })) {
        record(rec, event, new Date(createdAt.getTime() + at).toISOString());
      }
      rec.finished = true;
      return this.snapshot(rec);
    });
    await this.saveJobs(snaps);
    return snaps.length;
  }

  /** 即時事件：保存後轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
    const message = record(rec, e, this.now().toISOString());
    for (const listener of rec.listeners) this.deliver(listener, message);
  }

  /** 任務結束時保存到本機：重新整理後，Agent 透視與成效儀表板仍看得到 */
  private persist(rec: JobRecord): Promise<void> {
    return this.saveJobs([this.snapshot(rec)]).catch((err: unknown) => console.error('[MockApiClient] failed to save job', err));
  }

  private async storedJobs(): Promise<JobSnapshot[]> {
    return (await this.store.get<JobSnapshot[]>(KEYS.jobs)) ?? [];
  }

  /** 取代同 id 的舊紀錄；依建立時間由新到舊，只保留 MAX_STORED_JOBS 筆 */
  private saveJobs(snaps: JobSnapshot[]): Promise<void> {
    return this.serial(async () => {
      const ids = new Set(snaps.map((s) => s.summary.id));
      const kept = (await this.storedJobs()).filter((s) => !ids.has(s.summary.id));
      const all = [...snaps, ...kept].sort((a, b) => b.summary.createdAt.localeCompare(a.summary.createdAt));
      await this.store.set(KEYS.jobs, all.slice(0, MAX_STORED_JOBS));
    });
  }

  /** 記憶體中的任務；不在記憶體時從本機紀錄還原（已結束的任務） */
  private async loadJob(jobId: string): Promise<JobRecord | null> {
    const live = this.jobs.get(jobId);
    if (live) return live;
    const snap = (await this.storedJobs()).find((s) => s.summary.id === jobId);
    if (!snap) return null;
    // 讀取期間可能已被另一個呼叫還原
    const loaded = this.jobs.get(jobId);
    if (loaded) return loaded;
    const rec = newRecord(jobId, snap.summary.input, snap.summary.createdAt);
    for (const m of snap.events) {
      apply(rec, m);
      rec.events.push(Object.freeze(m));
    }
    rec.finished = true;
    this.jobs.set(jobId, rec);
    return rec;
  }

  private async requireJob(jobId: string): Promise<JobRecord> {
    const rec = await this.loadJob(jobId);
    if (!rec) throw new Error(`Unknown job: ${jobId}`);
    return rec;
  }

  /** 單一訂閱者出錯不可中斷整條事件流（與 WebSocket 各自處理訊息的行為一致）；即時推送與重播共用 */
  private deliver<E extends { type: string }>(listener: (e: E) => void, e: E) {
    try {
      listener(e);
    } catch (err) {
      console.error('[MockApiClient] subscriber threw while handling', e.type, err);
    }
  }

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
    let active = true;
    const attach = (rec: JobRecord) => {
      for (const e of rec.events) this.deliver(onEvent, e);
      rec.listeners.add(onEvent);
    };
    const fail = (error: Error) => {
      if (onError) onError(error);
      else console.error('[MockApiClient]', error.message);
    };
    const live = this.jobs.get(jobId);
    if (live) attach(live);
    else {
      // 不在記憶體時從本機紀錄還原；找不到時與 WebSocket 一樣非同步回報
      void this.loadJob(jobId).then(
        (rec) => {
          if (!active) return;
          if (rec) attach(rec);
          else fail(new Error(`Unknown job: ${jobId}`));
        },
        (err: unknown) => {
          if (active) fail(err instanceof Error ? err : new Error(String(err)));
        },
      );
    }
    return () => {
      active = false;
      this.jobs.get(jobId)?.listeners.delete(onEvent);
    };
  }

  private summary(rec: JobRecord): JobSummary {
    return {
      id: rec.id, input: structuredClone(rec.input), createdAt: rec.createdAt, stage: rec.stage, round: rec.round,
      finished: rec.finished, bestRenderIds: { ...rec.bestRenderIds },
    };
  }

  private snapshot(rec: JobRecord): JobSnapshot {
    return { summary: this.summary(rec), events: [...rec.events] };
  }

  /** 記憶體中的任務 + 本機保存的已結束任務 */
  async listJobs(): Promise<JobSummary[]> {
    const live = [...this.jobs.values()].reverse().map((rec) => this.summary(rec));
    const ids = new Set(live.map((j) => j.id));
    const stored = (await this.storedJobs()).filter((s) => !ids.has(s.summary.id)).map((s) => s.summary);
    // 穩定排序：同一時間建立的任務維持原本的先後
    return [...live, ...stored].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  async getJob(jobId: string): Promise<JobSnapshot> {
    return this.snapshot(await this.requireJob(jobId));
  }

  async cancelJob(jobId: string): Promise<void> {
    // 執行中的任務一定在記憶體：同步取消，在事件處理函式內呼叫時會立刻停止後續事件
    const rec = this.jobs.get(jobId) ?? (await this.requireJob(jobId));
    if (rec.finished) return;
    rec.player?.cancel();
    rec.finished = true;
    this.dispatch(rec, { type: 'job.status', stage: 'cancelled', round: rec.round });
    await this.persist(rec);
  }

  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry> {
    return this.serial(async () => {
      const rec = await this.requireJob(jobId);
      const render = rec.renders.get(renderId);
      if (!render) throw new Error(`Unknown render: ${renderId}`);
      const entry: HistoryEntry = {
        id: makeId('hist'), jobId, brandId: rec.input.brandId, productId: rec.input.productId, input: structuredClone(rec.input),
        templateId: render.templateId, render: structuredClone(render), copy: structuredClone(copy), selectedAt: this.now().toISOString(),
        favorite: false, writtenToRag: true,
      };
      const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
      await this.store.set(KEYS.history, [entry, ...history]);
      return entry;
    });
  }

  async listHistory(brandId?: string): Promise<HistoryEntry[]> {
    const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
    return brandId ? history.filter((h) => h.brandId === brandId) : history;
  }

  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry> {
    return this.serial(async () => {
      const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
      const entry = history.find((h) => h.id === historyId);
      if (!entry) throw new Error(`Unknown history entry: ${historyId}`);
      const updated = { ...entry, favorite };
      await this.store.set(KEYS.history, history.map((h) => (h.id === historyId ? updated : h)));
      return updated;
    });
  }
}
