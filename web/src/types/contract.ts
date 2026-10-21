/**
 * 前後端資料約定。第二階段 FastAPI 以 Pydantic 照此定義，
 * WebSocket `/ws/jobs/{jobId}` 送出的訊息是 `JobMessage`（`JobEvent` 加上序號與時間戳）。
 */

export const TEMPLATE_IDS = ['ecom-main', 'scene', 'ig-post', 'story', 'banner'] as const;
export type TemplateId = (typeof TEMPLATE_IDS)[number];

export const LAYOUT_ELEMENT_IDS = ['logo', 'headline', 'subhead', 'features', 'product', 'badge', 'price', 'disclaimer'] as const;
export type LayoutElementId = (typeof LAYOUT_ELEMENT_IDS)[number];

export const CHECK_IDS = [
  'banned_words', 'color_delta', 'logo_clearance', 'disclaimer', 'product_ratio', 'whitespace', 'ocr_typo',
  'vlm_exaggeration', 'vlm_occlusion', 'vlm_quality',
] as const;
export type CheckId = (typeof CHECK_IDS)[number];

export const TONES = ['gentle', 'science', 'playful', 'minimal'] as const;
export type Tone = (typeof TONES)[number];

export type Hex = `#${string}`;
export interface Palette { primary: Hex; secondary: Hex; accent: Hex; ink: Hex }
export type Engine = 'comfyui' | 'ideogram';

/** [x, y, w, h]，單位為輸出圖的像素 */
export type BBox = [x: number, y: number, w: number, h: number];
export interface LayoutBox { id: LayoutElementId; bbox: BBox; z: number }

/* ---------- 品牌與 RAG ---------- */
/** general：使用者上傳、無法歸類的文件切塊 */
export type RagTag = 'color' | 'logo' | 'law' | 'layout' | 'font' | 'history' | 'general';
export interface RagChunk { id: string; source: string; section: string; tag: RagTag; text: string }
export interface CaseStudy { id: string; title: string; channel: string; ctr: number; notes: string }
export interface BrandRules { maxDeltaE: number; minWhitespace: number; productRatio: [min: number, max: number] }

export interface Brand {
  id: string;
  name: string;
  category: string;
  ciVersion: string;
  palette: Palette;
  fonts: { headline: string; body: string };
  /** 生圖時的品牌視覺風格描述（英文，直接進 positive prompt） */
  visualStyle: string;
  defaultTone: Tone;
  rules: BrandRules;
  /** 禁用詞（法規與品牌規範） */
  bannedWords: string[];
  /** 合規替代用語：禁用詞 → 替代詞（空字串代表刪除） */
  replacements: Record<string, string>;
  /** 出現這些詞視為效果宣稱 */
  claimWords: string[];
  /** 效果宣稱時頁尾必須包含的註記；空字串代表此品牌不需要 */
  disclaimerPhrase: string;
  guidelineChunks: RagChunk[];
  caseStudies: CaseStudy[];
  copyPresets: Record<Tone, { headline: [string, string]; subhead: string }>;
  /** Logo 圖檔；null 時排版以向量標誌加品牌名稱繪製 */
  logo: { url: string } | null;
}

/* ---------- 商品與模板 ---------- */
export type ProductPhoto =
  | { source: 'sample'; art: 'serum' | 'coldbrew' }
  | { source: 'upload' | 'local'; url: string };

/** 去背結果。url 為 null 代表示意：mock 不真的去背，合成時以「色彩增值」讓白底融入背景 */
/** 去背結果：pending 去背中、done 完成（url 為透明 PNG；mock 的示意為 null）、failed 失敗（error 為原因） */
export type CutoutStatus = 'pending' | 'done' | 'failed';
export interface ProductCutout { model: string; status: CutoutStatus; url: string | null; error: string | null }

export interface Product {
  id: string;
  brandId: string;
  name: string;
  features: string[];
  price: { sale: number; original: number };
  photo: ProductPhoto;
  /** 尚未去背為 null；示範商品是向量素材，不需要去背 */
  cutout: ProductCutout | null;
  createdAt: string;
}

export interface ChannelTemplate { id: TemplateId; label: string; ratio: string; width: number; height: number }

/* ---------- 任務輸入 ---------- */
export interface ParsedBrief {
  productName: string | null;
  sellingPoints: string[];
  audience: string;
  tone: Tone;
  campaign: string | null;
  offer: string | null;
  /** 活動期間，例如 10/15–11/15；需求沒有提到時為 null */
  period: string | null;
  /** 英文風格標籤，例如 minimal、premium */
  style: string[];
}

export interface JobInput {
  brandId: string;
  productId: string;
  brief: string;
  parsedBrief: ParsedBrief;
  templateIds: TemplateId[];
  variantsPerTemplate: number;
  llm: string;
  engine: Engine;
  vlm: string;
  maxRetries: number;
}

/* ---------- Agent 輸出 ---------- */
export interface Copy {
  headline: [string, string];
  subhead: string;
  features: string[];
  badge: { top: string; main: string; sub: string };
  price: { label: string; sale: number; original: number };
  productName: string;
  disclaimer: string;
}

export interface ComfyParam { nodeId: string; input: string; label: string; value: string | number }
export interface ComfyInjection { engine: Engine; workflowFile: string; params: ComfyParam[] }

export interface PromptSpec {
  jobId: string;
  round: number;
  templateId: TemplateId;
  brandId: string;
  canvas: { width: number; height: number; ratio: string };
  palette: Palette;
  copy: Copy;
  layout: LayoutBox[];
  positivePrompt: string;
  negativePrompt: string;
  injection: ComfyInjection;
  ragRefs: string[];
}

/* ---------- 審查與產出 ---------- */
export type CheckStatus = 'pass' | 'warn' | 'fail';
export interface ReviewCheck {
  id: CheckId;
  name: string;
  kind: 'rule' | 'vlm';
  rule: string;
  value: string;
  status: CheckStatus;
  /** 對應版面元素；'canvas' 代表整張圖；null 代表無特定位置 */
  target: LayoutElementId | 'canvas' | null;
  ragRef: string | null;
}

export type RenderBackground =
  | { kind: 'procedural'; seed: number; palette: Palette; style: string }
  /** includesProduct：生成圖已包含商品（ComfyUI 打光融合後），繪製時跳過商品圖層 */
  | { kind: 'url'; url: string; includesProduct: boolean };

export interface Render {
  id: string;
  jobId: string;
  round: number;
  templateId: TemplateId;
  variant: number;
  background: RenderBackground;
  spec: PromptSpec;
  score: number | null;
  passed: boolean | null;
  checks: ReviewCheck[];
}

export interface RagHit {
  chunkId: string;
  source: string;
  section: string;
  tag: RagTag;
  text: string;
  vectorScore: number;
  rerankScore?: number;
}

export interface Fix { checkId: CheckId; title: string; desc: string }

/* ---------- WebSocket 事件 ---------- */
export type JobStage =
  | 'queued' | 'parsing' | 'retrieving' | 'prompting' | 'rendering' | 'composing' | 'reviewing'
  | 'rewriting' | 'saving' | 'done' | 'needs_review' | 'cancelled' | 'failed';
export type RenderNode = 'cutout' | 'generate' | 'relight' | 'upscale';
export type LogSource = 'ws' | 'api' | 'agent' | 'rag' | 'comfy' | 'compose' | 'vlm' | 'db';
export type LogLevel = 'info' | 'ok' | 'warn' | 'error';

export type JobEvent =
  | { type: 'job.accepted'; jobId: string }
  | { type: 'job.status'; stage: JobStage; round: number }
  | { type: 'brief.parsed'; parsedBrief: ParsedBrief }
  | { type: 'rag.retrieved'; query: string; hits: RagHit[] }
  | { type: 'rag.reranked'; hits: RagHit[] }
  | { type: 'prompt.generated'; round: number; templateId: TemplateId; spec: PromptSpec }
  | { type: 'comfy.queued'; round: number; templateId: TemplateId; promptId: string; injection: ComfyInjection }
  | { type: 'render.progress'; round: number; node: RenderNode; step: number; maxStep: number }
  | { type: 'render.completed'; round: number; renders: Render[] }
  | { type: 'review.check'; round: number; renderId: string; check: ReviewCheck }
  | { type: 'review.completed'; round: number; renderId: string; score: number; passed: boolean }
  | { type: 'rewrite.started'; round: number; templateId: TemplateId; reasons: CheckId[]; fixes: Fix[]; requery: boolean }
  | { type: 'job.completed'; jobId: string; bestRenderIds: Partial<Record<TemplateId, string>> }
  | { type: 'job.needs_review'; jobId: string; reason: string }
  /** 技術故障（外部服務無回應、worker 重新啟動等），與「需人工審核」不同 */
  | { type: 'job.failed'; jobId: string; reason: string }
  | { type: 'log'; source: LogSource; level: LogLevel; message: string };

/**
 * 每則事件訊息附帶的序號與時間戳。
 * seq：同一任務內從 1 開始連續遞增，重新連線時用來補齊漏掉的事件；ts：後端送出時間（ISO 8601）。
 */
export interface EventMeta { seq: number; ts: string }
export type JobMessage = JobEvent & EventMeta;

/* ---------- 歷史紀錄與 Demo ---------- */
export interface HistoryEntry {
  id: string;
  jobId: string;
  brandId: string;
  productId: string;
  input: JobInput;
  templateId: TemplateId;
  render: Render;
  copy: Copy;
  selectedAt: string;
  favorite: boolean;
  writtenToRag: boolean;
}

export interface DemoOptions { speed: 1 | 2 | 4; firstRoundFail: boolean; forceAllFail: boolean }

/* ---------- 任務列表與連線狀態 ---------- */
export interface JobSummary {
  id: string;
  input: JobInput;
  createdAt: string;
  stage: JobStage;
  round: number;
  /** 已結束（done／needs_review／cancelled／failed） */
  finished: boolean;
  /** 任務完成時每個模板的最佳候選；尚未完成或需人工審核時為空物件 */
  bestRenderIds: Partial<Record<TemplateId, string>>;
}

/* ---------- 品牌文件上傳（chunking → embedding → 寫入 Chroma） ---------- */
export type IngestEvent =
  | { type: 'ingest.chunked'; source: string; chunks: RagChunk[] }
  | { type: 'ingest.embedded'; chunkId: string; index: number; total: number; dims: number; preview: number[] }
  | { type: 'ingest.stored'; collection: string; count: number };

/* ---------- 成效儀表板 ---------- */
export interface CheckFailureStat { checkId: CheckId; name: string; kind: 'rule' | 'vlm'; fail: number; warn: number }

/**
 * Rerank 對命中率的影響：前 k 筆檢索結果涵蓋了多少「審查未通過項目所引用的規範」。
 * vector 為向量召回的順序，rerank 為 BGE Rerank 後的順序；值為 0–1，取各任務平均。
 */
export interface RerankHitStat { k: number; vector: number; rerank: number }

export interface JobStat {
  jobId: string;
  brandId: string;
  createdAt: string;
  outcome: 'done' | 'needs_review';
  templates: number;
  /** 共跑了幾輪（1 代表沒有重試） */
  rounds: number;
  /** 生成的候選張數（含重試） */
  renders: number;
  /** 交付張數（各模板的最佳候選） */
  delivered: number;
  durationMs: number;
  costUsd: number;
}

export interface DashboardStats {
  /** 已結束的任務數（不含取消） */
  jobs: number;
  /** 審查過的候選張數 */
  renders: number;
  /** 任務通過率：完成 ÷（完成 + 需人工審核） */
  passRate: number;
  /** 第一輪就通過審查的模板比例 */
  firstPassRate: number;
  /** 每個任務平均重試幾輪 */
  avgRetries: number;
  avgDurationMs: number;
  /** 每張交付圖的平均成本（美元，估算）；沒有交付任何圖時為 null */
  costPerImage: number | null;
  /** 依 CHECK_IDS 的順序 */
  checkFailures: CheckFailureStat[];
  /** k = 1 到檢索筆數 */
  rerankHits: RerankHitStat[];
  /** 最近的任務，新到舊，最多 8 筆 */
  recent: JobStat[];
}

/* ---------- 本機資料夾、可用選項與系統狀態 ---------- */
/** assets/products/ 的照片（只有 live 模式由後端提供） */
export interface LocalPhoto {
  file: string;
  /** 檔名去掉副檔名，底線與連字號換成空白 */
  name: string;
  url: string;
  size: number;
}

/** 目前可用的 LLM、VLM 與生圖引擎（顯示名稱即 JobInput 的值） */
export interface ApiOptions { llm: string[]; vlm: string[]; engines: Engine[] }

/** ok 正常、sim 使用模擬版、off 未啟用、error 異常 */
export interface ComponentStatus { id: string; label: string; status: 'ok' | 'sim' | 'off' | 'error'; detail: string }
export interface SystemStatus { components: ComponentStatus[] }

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
export interface ConnectionState {
  status: ConnectionStatus;
  /** mock：瀏覽器內模擬；websocket：連線 FastAPI（第二階段） */
  transport: 'mock' | 'websocket';
  error: string | null;
}
