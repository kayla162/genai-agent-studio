export const round1 = (v: number): number => Math.round(v * 10) / 10;

export const clamp = (v: number, min: number, max: number): number => Math.min(max, Math.max(min, v));

/** 可重現的偽隨機數產生器（同一 seed 產生同一序列） */
export function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a 32-bit 字串雜湊，回傳非負整數 */
export function hashString(s: string): number {
  let h = 2166136261;
  for (const ch of s) {
    h ^= ch.codePointAt(0) ?? 0;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
