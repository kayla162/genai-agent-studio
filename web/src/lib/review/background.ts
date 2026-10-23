import type { ReviewCheck } from '@/types/contract';

/** 背景色系外的面積比例 ≤ 這個值為通過（實驗決定，Plan 7 規格 §4.8） */
export const BG_PASS_MAX = 0.15;
/** 背景色系外的面積比例 ≤ 這個值為警告，超過為不通過（實驗決定） */
export const BG_WARN_MAX = 0.3;

/** 背景色系的量測結果（composer 從疊上文字與商品之前的背景量出；Plan 7 規格 §4.8） */
export interface BackgroundPalette {
  /** 商品方框以外、品牌色系外的像素比例（0–1） */
  offShare: number;
  /** 色系外像素中最多的顏色（#RRGGBB）；沒有色系外的像素時為 null */
  offHex: string | null;
  /** 量測的像素數 */
  sampled: number;
}

/** 背景色系檢查說明中色系外的主要顏色：`色系外 42%（主要為 #3FD27A）`（hex 為大寫） */
export const OFF_PALETTE_LABEL = '主要為';
const OFF_PALETTE_PATTERN = new RegExp(`${OFF_PALETTE_LABEL} (#[0-9A-F]{6})）$`);

/**
 * 背景色系檢查（bg_palette）的判定。沒有量測結果（模擬模式、前端 mock）時為通過，說明為「（模擬）」，
 * 與 VLM 模擬檢查的標示一致。
 */
export function bgPaletteCheck(result: BackgroundPalette | null | undefined): Pick<ReviewCheck, 'value' | 'status' | 'target'> {
  if (!result) return { value: '（模擬）', status: 'pass', target: 'canvas' };
  const pct = Math.round(result.offShare * 100);
  const hex = result.offHex?.toUpperCase() ?? null;
  const status = result.offShare <= BG_PASS_MAX ? 'pass' : result.offShare <= BG_WARN_MAX ? 'warn' : 'fail';
  const value = status !== 'pass' && hex ? `色系外 ${pct}%（${OFF_PALETTE_LABEL} ${hex}）` : `色系外 ${pct}%`;
  return { value, status, target: 'canvas' };
}

/** 背景色系檢查說明文字裡色系外的主要顏色（#RRGGBB）；其他檢查或沒有時為 null。審查面板依此畫出色塊。 */
export function measuredBackgroundOf(check: Pick<ReviewCheck, 'id' | 'value'>): string | null {
  return check.id === 'bg_palette' ? (OFF_PALETTE_PATTERN.exec(check.value)?.[1] ?? null) : null;
}
