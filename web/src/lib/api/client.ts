import type {
  Brand, ChannelTemplate, ConnectionState, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, JobSummary, ParsedBrief,
  Product,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
}

export interface ConnectionChannel {
  /** 狀態沒變時回傳同一個物件（可直接給 useSyncExternalStore 使用） */
  get(): ConnectionState;
  /** 狀態改變時通知；回傳取消訂閱的函式 */
  subscribe(listener: (state: ConnectionState) => void): () => void;
}

export interface JobSnapshot { summary: JobSummary; events: JobEvent[] }

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  listBrands(): Promise<Brand[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  /** 最新的任務在前 */
  listJobs(): Promise<JobSummary[]>;
  getJob(jobId: string): Promise<JobSnapshot>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
}
