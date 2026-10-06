import type {
  Brand, ChannelTemplate, Copy, DemoOptions, HistoryEntry, JobEvent, JobInput, ParsedBrief, Product,
} from '@/types/contract';

export type ProductDraft = Omit<Product, 'id' | 'createdAt'> & { id?: string };

export interface DemoControls {
  get(): DemoOptions;
  set(patch: Partial<DemoOptions>): void;
}

/** UI 只依賴這個介面：第一階段由 MockApiClient 實作，第二階段由連線 FastAPI 的 HttpApiClient 實作 */
export interface ApiClient {
  /** 只有 mock 模式有 Demo 控制台；live 模式為 null */
  readonly demo: DemoControls | null;
  listBrands(): Promise<Brand[]>;
  listTemplates(): Promise<ChannelTemplate[]>;
  listProducts(brandId: string): Promise<Product[]>;
  saveProduct(draft: ProductDraft): Promise<Product>;
  deleteProduct(id: string): Promise<void>;
  parseBrief(brandId: string, text: string, productId: string | null): Promise<ParsedBrief>;
  createJob(input: JobInput): Promise<{ jobId: string }>;
  /** 先重播已發生的事件，再接收即時事件；回傳取消訂閱的函式 */
  subscribe(jobId: string, onEvent: (event: JobEvent) => void): () => void;
  cancelJob(jobId: string): Promise<void>;
  selectRender(jobId: string, renderId: string, copy: Copy): Promise<HistoryEntry>;
  listHistory(brandId?: string): Promise<HistoryEntry[]>;
}
