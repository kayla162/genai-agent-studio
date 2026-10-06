import type { Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, Product, Render } from '@/types/contract';
import type { ApiClient, DemoControls, ProductDraft } from '../client';
import { CHANNEL_TEMPLATES, getTemplate } from '@/lib/compose/templates';
import { hashString } from '@/lib/core/num';
import { BRANDS, getBrandById, SAMPLE_PRODUCTS } from './data';
import { parseBrief } from './brief';
import { playTimeline, type PlayerHandle } from './player';
import { buildTimeline } from './scenario';
import { MemoryStore, type KeyValueStore } from './store';

interface JobRecord {
  id: string;
  input: JobInput;
  events: JobEvent[];
  listeners: Set<(e: JobEvent) => void>;
  renders: Map<string, Render>;
  round: number;
  finished: boolean;
  player: PlayerHandle | null;
}

const KEYS = { products: 'products', deleted: 'deletedSampleIds', history: 'history' } as const;
const pad = (n: number) => String(n).padStart(2, '0');

export function makeJobId(now: Date, rand: () => number = Math.random): string {
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `job_${date}_${time}_${Math.floor(rand() * 0xffff).toString(16).padStart(4, '0')}`;
}

const makeId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class MockApiClient implements ApiClient {
  readonly demo: DemoControls;
  private options: DemoOptions = { speed: 1, firstRoundFail: true, forceAllFail: false };
  private readonly jobs = new Map<string, JobRecord>();

  constructor(
    private readonly store: KeyValueStore = new MemoryStore(),
    private readonly now: () => Date = () => new Date(),
  ) {
    this.demo = {
      get: () => ({ ...this.options }),
      set: (patch) => { this.options = { ...this.options, ...patch }; },
    };
  }

  async listBrands() { return BRANDS; }

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

  async saveProduct(draft: ProductDraft): Promise<Product> {
    getBrandById(draft.brandId);
    const custom = await this.customProducts();
    const existing = draft.id
      ? (custom.find((p) => p.id === draft.id) ?? SAMPLE_PRODUCTS.find((p) => p.id === draft.id))
      : undefined;
    const product: Product = { ...draft, id: draft.id ?? makeId('prod'), createdAt: existing?.createdAt ?? this.now().toISOString() };
    await this.store.set(KEYS.products, [...custom.filter((p) => p.id !== product.id), product]);
    return product;
  }

  async deleteProduct(id: string): Promise<void> {
    const custom = await this.customProducts();
    await this.store.set(KEYS.products, custom.filter((p) => p.id !== id));
    if (SAMPLE_PRODUCTS.some((p) => p.id === id)) {
      const deleted = (await this.store.get<string[]>(KEYS.deleted)) ?? [];
      await this.store.set(KEYS.deleted, [...new Set([...deleted, id])]);
    }
  }

  private async findProduct(id: string): Promise<Product> {
    const p = (await this.customProducts()).find((x) => x.id === id) ?? SAMPLE_PRODUCTS.find((x) => x.id === id);
    if (!p) throw new Error(`Unknown product: ${id}`);
    return p;
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
    const templates = input.templateIds.map((id) => getTemplate(id));

    const jobId = makeJobId(this.now());
    const rec: JobRecord = {
      id: jobId, input, events: [], listeners: new Set(), renders: new Map(), round: 0, finished: false, player: null,
    };
    this.jobs.set(jobId, rec);

    const timeline = buildTimeline({ jobId, input, brand, product, templates, demo: this.demo.get(), seed: hashString(jobId) });
    rec.player = playTimeline(timeline, {
      getSpeed: () => this.options.speed,
      onEvent: (e) => this.dispatch(rec, e),
      onDone: () => { rec.finished = true; },
    });
    return { jobId };
  }

  /** 更新任務狀態（給 selectRender 用），再轉發給訂閱者 */
  private dispatch(rec: JobRecord, e: JobEvent) {
    switch (e.type) {
      case 'job.status':
        rec.round = e.round;
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
    rec.events.push(e);
    for (const listener of rec.listeners) listener(e);
  }

  private getJob(jobId: string): JobRecord {
    const rec = this.jobs.get(jobId);
    if (!rec) throw new Error(`Unknown job: ${jobId}`);
    return rec;
  }

  subscribe(jobId: string, onEvent: (event: JobEvent) => void): () => void {
    const rec = this.getJob(jobId);
    for (const e of rec.events) onEvent(e);
    rec.listeners.add(onEvent);
    return () => { rec.listeners.delete(onEvent); };
  }

  async cancelJob(jobId: string): Promise<void> {
    const rec = this.getJob(jobId);
    if (rec.finished) return;
    rec.player?.cancel();
    rec.finished = true;
    this.dispatch(rec, { type: 'job.status', stage: 'cancelled', round: rec.round });
  }

  async selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry> {
    const rec = this.getJob(jobId);
    const render = rec.renders.get(renderId);
    if (!render) throw new Error(`Unknown render: ${renderId}`);
    const entry: HistoryEntry = {
      id: makeId('hist'), jobId, brandId: rec.input.brandId, productId: rec.input.productId, templateId: render.templateId,
      render: structuredClone(render), copy: structuredClone(copy), selectedAt: this.now().toISOString(),
      favorite: false, writtenToRag: true,
    };
    const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
    await this.store.set(KEYS.history, [entry, ...history]);
    return entry;
  }

  async listHistory(brandId?: string): Promise<HistoryEntry[]> {
    const history = (await this.store.get<HistoryEntry[]>(KEYS.history)) ?? [];
    return brandId ? history.filter((h) => h.brandId === brandId) : history;
  }
}
