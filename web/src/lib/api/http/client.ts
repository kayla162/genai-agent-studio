import type {
  ApiOptions, Brand, ChannelTemplate, Copy, DashboardStats, HistoryEntry, IngestEvent, JobInput, JobMessage,
  JobSummary, LocalPhoto, ParsedBrief, Product, ProductPhoto, RagChunk, SystemStatus,
} from '@/types/contract';
import type { ApiClient, JobSnapshot, ProductDraft } from '../client';
import { ConnectionTracker } from './connection';
import { openJobSocket, RECONNECT_DELAY } from './job-socket';

/** 後端回傳的錯誤（{ error: { code, message } }，message 為繁體中文，可直接顯示） */
export class ApiError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface HttpApiClientOptions {
  /** 後端網址；省略時同源（正式版由 nginx、開發時由 next dev 的 rewrites 轉給 api） */
  baseUrl?: string;
  fetch?: typeof fetch;
  WebSocket?: typeof WebSocket;
}

type IngestLine = IngestEvent | { error: { code: string; message: string } };

const q = encodeURIComponent;
const query = (brandId?: string) => (brandId ? `?brandId=${q(brandId)}` : '');
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } };
    if (body.error?.message) return new ApiError(body.error.code ?? 'error', body.error.message, res.status);
  } catch {
    // 不是後端的 JSON（例如 nginx 的錯誤頁）
  }
  return new ApiError('http_error', `後端回應 HTTP ${res.status}`, res.status);
}

/** 逐行讀取 NDJSON（一個 chunk 可能含多行，也可能只有半行） */
async function* readLines(res: Response): AsyncGenerator<string> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = done ? '' : (lines.pop() ?? '');
    for (const line of lines) if (line.trim()) yield line;
    if (done) return;
  }
}

/** live 模式：連線 FastAPI。REST 使用 fetch；任務事件使用 WebSocket，斷線後以最後的 seq 重新連線。 */
export class HttpApiClient implements ApiClient {
  readonly demo = null;
  readonly connection: ConnectionTracker;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly WebSocketImpl: typeof WebSocket;
  private probing = false;

  constructor(options: HttpApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '';
    // 不可直接存 fetch 再以 this.fetchImpl() 呼叫：瀏覽器會丟出 Illegal invocation
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init));
    this.WebSocketImpl = options.WebSocket ?? WebSocket;
    this.connection = new ConnectionTracker(() => void this.probe());
  }

  /** 送出請求；連不上後端時更新連線狀態，非 2xx 時丟出 ApiError */
  private async send(path: string, init: RequestInit = {}): Promise<Response> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, init);
    } catch {
      this.lost('無法連線到後端');
      throw new ApiError('network', '無法連線到後端，請確認服務已啟動', 0);
    }
    // 502、504：nginx 連不上 api
    if (res.status === 502 || res.status === 504) this.lost(`後端沒有回應（HTTP ${res.status}）`);
    else this.connection.set('connected');
    if (!res.ok) throw await toApiError(res);
    return res;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { 'content-type': 'application/json' };
    }
    const res = await this.send(path, init);
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  private lost(error: string) {
    this.connection.set('disconnected', error);
    if (this.connection.watched) void this.probe();
  }

  /** 連線中斷時定期確認後端是否恢復（有人看連線狀態時才做） */
  private async probe() {
    if (this.probing) return;
    this.probing = true;
    try {
      for (let delay = RECONNECT_DELAY.min; ; delay = Math.min(delay * 2, RECONNECT_DELAY.max)) {
        try {
          await this.send('/api/health');
          return;
        } catch {
          await sleep(delay);
        }
      }
    } finally {
      this.probing = false;
    }
  }

  private socketUrl(path: string): string {
    const url = new URL(path, this.baseUrl || window.location.origin);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.toString();
  }

  getOptions(): Promise<ApiOptions> {
    return this.request('GET', '/api/options');
  }

  getSystemStatus(): Promise<SystemStatus> {
    return this.request('GET', '/api/status');
  }

  listBrands(): Promise<Brand[]> {
    return this.request('GET', '/api/brands');
  }

  /** 以 multipart 上傳原檔（欄位 file）；檔案的問題在開始串流之前就以 HTTP 400 回應 */
  async ingestBrandDocument(brandId: string, file: File, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]> {
    const form = new FormData();
    form.append('file', file, file.name);
    const res = await this.send(`/api/brands/${q(brandId)}/documents`, { method: 'POST', body: form });
    let chunks: RagChunk[] = [];
    for await (const line of readLines(res)) {
      const message = JSON.parse(line) as IngestLine;
      if ('error' in message) throw new ApiError(message.error.code, message.error.message, res.status);
      if (message.type === 'ingest.chunked') chunks = message.chunks;
      try {
        onEvent(message);
      } catch (err) {
        console.error('[HttpApiClient] ingest listener threw while handling', message.type, err);
      }
      if (message.type === 'ingest.stored') return chunks;
    }
    throw new ApiError('network', '文件上傳的進度中斷，請重新整理後確認知識庫', 0);
  }

  listTemplates(): Promise<ChannelTemplate[]> {
    return this.request('GET', '/api/templates');
  }

  listProducts(brandId: string): Promise<Product[]> {
    return this.request('GET', `/api/products${query(brandId)}`);
  }

  saveProduct(draft: ProductDraft): Promise<Product> {
    // 只送 ProductDraft 的欄位：呼叫端常傳入整個商品（含 createdAt），後端會拒絕多餘欄位
    const { id, brandId, name, features, price, photo, cutout } = draft;
    const body: ProductDraft = { brandId, name, features, price, photo, cutout };
    return id ? this.request('PUT', `/api/products/${q(id)}`, { ...body, id }) : this.request('POST', '/api/products', body);
  }

  deleteProduct(id: string): Promise<void> {
    return this.request('DELETE', `/api/products/${q(id)}`);
  }

  uploadProductPhoto(file: Blob): Promise<ProductPhoto> {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'photo');
    return this.request('POST', '/api/products/photos', form);
  }

  requestCutout(productId: string): Promise<Product> {
    return this.request('POST', `/api/products/${q(productId)}/cutout`);
  }

  listLocalPhotos(): Promise<LocalPhoto[] | null> {
    return this.request('GET', '/api/local-photos');
  }

  importLocalPhoto(file: string, brandId: string): Promise<Product> {
    return this.request('POST', `/api/local-photos/${q(file)}/import`, { brandId });
  }

  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief> {
    return this.request('POST', '/api/briefs/parse', { brandId, text, productId });
  }

  createJob(input: JobInput): Promise<{ jobId: string }> {
    return this.request('POST', '/api/jobs', input);
  }

  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void {
    return openJobSocket(jobId, onEvent, onError ?? ((err) => console.error('[HttpApiClient]', err.message)), {
      url: (after) => this.socketUrl(`/ws/jobs/${q(jobId)}?after=${after}`),
      WebSocket: this.WebSocketImpl,
      connection: this.connection,
    });
  }

  cancelJob(jobId: string): Promise<void> {
    return this.request('POST', `/api/jobs/${q(jobId)}/cancel`);
  }

  listJobs(): Promise<JobSummary[]> {
    return this.request('GET', '/api/jobs');
  }

  getJob(jobId: string): Promise<JobSnapshot> {
    return this.request('GET', `/api/jobs/${q(jobId)}`);
  }

  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry> {
    return this.request('POST', `/api/jobs/${q(jobId)}/select`, { renderId, copy });
  }

  listHistory(brandId?: string): Promise<HistoryEntry[]> {
    return this.request('GET', `/api/history${query(brandId)}`);
  }

  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry> {
    return this.request('PATCH', `/api/history/${q(historyId)}`, { favorite });
  }

  getDashboardStats(brandId?: string): Promise<DashboardStats> {
    return this.request('GET', `/api/stats${query(brandId)}`);
  }
}
