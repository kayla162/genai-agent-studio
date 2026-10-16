import type {
  ApiOptions, Brand, BrandDocument, ChannelTemplate, ConnectionState, Copy, DashboardStats, DemoOptions, HistoryEntry,
  IngestEvent, JobInput, JobMessage, JobSummary, LocalPhoto, ParsedBrief, Product, ProductPhoto, RagChunk, SystemStatus,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
  /** 直接產生 count 筆已結束的示範任務（不播放），讓成效儀表板有資料；回傳新增筆數 */
  seedJobs(count: number): Promise<number>;
}

export interface ConnectionChannel {
  /** 狀態沒變時回傳同一個物件（可直接給 useSyncExternalStore 使用） */
  get(): ConnectionState;
  /** 狀態改變時通知；回傳取消訂閱的函式 */
  subscribe(listener: (state: ConnectionState) => void): () => void;
}

export interface JobSnapshot { summary: JobSummary; events: JobMessage[] }

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  readonly connection: ConnectionChannel;
  /** 目前可用的 LLM、VLM 與生圖引擎 */
  getOptions(): Promise<ApiOptions>;
  /** 各服務的狀態（資料庫、佇列、向量庫、composer、ComfyUI、Gemini） */
  getSystemStatus(): Promise<SystemStatus>;
  /** 包含使用者上傳文件產生的切塊 */
  listBrands(): Promise<Brand[]>;
  /** 上傳品牌文件：切塊 → 向量化 → 寫入知識庫，過程以 onEvent 回報；回傳新增的切塊 */
  ingestBrandDocument(brandId: string, doc: BrandDocument, onEvent: (e: IngestEvent) => void): Promise<RagChunk[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  /** 上傳商品照，回傳可放進 Product.photo 的參照（mock：轉成 data URL 存在本機；live：上傳到後端） */
  uploadProductPhoto(file: Blob): Promise<ProductPhoto>;
  /** 重新去背：把商品設為去背中並排入佇列，立即回傳商品（cutout 可能是 pending；之後重新讀取清單才看得到結果）。mock 約 1.2 秒後完成 */
  requestCutout(productId: string): Promise<Product>;
  /** 列出 assets/products/ 的照片；此模式無法讀取本機資料夾時回傳 null */
  listLocalPhotos(): Promise<LocalPhoto[] | null>;
  /** 把 assets/products/ 的照片匯入成商品（檔名當商品名稱） */
  importLocalPhoto(file: string, brandId: string): Promise<Product>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /**
   * 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式。事件附帶序號（seq）與時間戳（ts）。
   * 任務不存在或連線中斷時以 onError 非同步回報，不丟出例外（與 WebSocket 的行為一致）。
   */
  subscribe(jobId: string, onEvent: (event: JobMessage) => void, onError?: (error: Error) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  /** 最新的任務在前 */
  listJobs(): Promise<JobSummary[]>;
  getJob(jobId: string): Promise<JobSnapshot>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
  setFavorite(historyId: string, favorite: boolean): Promise<HistoryEntry>;
  /** 成效儀表板：統計已結束的任務；省略 brandId 時統計所有品牌 */
  getDashboardStats(brandId?: string): Promise<DashboardStats>;
}
