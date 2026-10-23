/**
 * Gemini 的結構化輸出與 composer 護欄的結果（AGENT_MODE=gemini）。
 * 後端的 backend/app/pipeline/gemini_types.py 定義同樣的欄位，以 contracts/fixtures/agent.json 確認一致；JSON 一律 camelCase。
 */
import type { BBox, LayoutElementId } from './contract';

/** Prompt 構建：Gemini 寫的文案、版面與生圖場景。色票、售價、商品名稱、註記與圖層順序由程式決定 */
export interface SpecDraft {
  headline: [string, string];
  subhead: string;
  /** 0–3 個 */
  features: string[];
  badge: { top: string; main: string; sub: string };
  priceLabel: string;
  /** 8 個元素各一個 [x, y, w, h]（畫布像素）；不含 z */
  layout: { id: LayoutElementId; bbox: BBox }[];
  /** 英文的生圖場景描述 */
  scene: string;
  /** 英文，加在負向提示詞後面 */
  negativeExtra: string;
  /** 一句中文，說明版面與文案的想法（顯示在 Agent 透視的 log） */
  rationale: string;
}

export type VlmStatus = 'pass' | 'warn' | 'fail';

/** VLM 審查：轉錄畫面上的文字，並判斷三項 VLM 檢查 */
export interface VlmVerdict {
  /** 畫面上所有文字，依閱讀順序一行一筆；看不清楚的字為「?」，方塊或無法辨識的符號為「□」 */
  lines: string[];
  /** 誇大或療效宣稱（依品牌類別判斷，不限於禁用詞） */
  exaggeration: { status: VlmStatus; phrases: string[]; reason: string };
  /** 文字或 Logo 被遮住、彼此重疊、與商品重疊 */
  occlusion: { status: VlmStatus; elements: LayoutElementId[]; reason: string };
  /** 構圖、光線、瑕疵、文字可讀性 */
  quality: { status: VlmStatus; issues: string[]; reason: string };
}

export const GUARD_CODES = [
  'emoji_removed', 'missing_glyph', 'banned_word', 'too_long', 'invented_offer', 'empty_field', 'product_glyph',
  'layout_invalid', 'layout_rule', 'text_too_small', 'prompt_invalid',
] as const;
export type GuardCode = (typeof GUARD_CODES)[number];

/** 護欄發現的問題。retry 為 true 的問題會讓 Agent 帶著 message 重問一次；仍有問題時該欄位改用預設 */
export interface GuardIssue {
  code: GuardCode;
  /** JSON 路徑，例如 headline.0、features.1、badge.main、layout、scene、productName */
  field: string;
  /** 中文說明，可直接接在重問的提示詞後面 */
  message: string;
  retry: boolean;
}
