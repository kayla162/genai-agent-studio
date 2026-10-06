/**
 * 前後端資料約定。第二階段 FastAPI 以 Pydantic 照此定義，
 * WebSocket `/ws/jobs/{jobId}` 送出的事件即 `JobEvent`。
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
export type RagTag = 'color' | 'logo' | 'law' | 'layout' | 'font' | 'history';
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
}

/* ---------- 商品與模板 ---------- */
export type ProductPhoto =
  | { source: 'sample'; art: 'serum' | 'coldbrew' }
  | { source: 'upload' | 'local'; url: string };

export interface Product {
  id: string;
  brandId: string;
  name: string;
  features: string[];
  price: { sale: number; original: number };
  photo: ProductPhoto;
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
  | { kind: 'url'; url: string };

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
  | 'parsing' | 'retrieving' | 'prompting' | 'rendering' | 'composing' | 'reviewing'
  | 'rewriting' | 'saving' | 'done' | 'needs_review' | 'cancelled';
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
  | { type: 'log'; source: LogSource; level: LogLevel; message: string };

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
  /** 已結束（done／needs_review／cancelled） */
  finished: boolean;
  /** 任務完成時每個模板的最佳候選；尚未完成或需人工審核時為空物件 */
  bestRenderIds: Partial<Record<TemplateId, string>>;
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
export interface ConnectionState {
  status: ConnectionStatus;
  /** mock：瀏覽器內模擬；websocket：連線 FastAPI（第二階段） */
  transport: 'mock' | 'websocket';
  error: string | null;
}
