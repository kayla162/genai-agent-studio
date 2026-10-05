/** 估算字串的視覺寬度（以 em 為單位）：中日文全形 1、空白 0.3、其他半形 0.58 */
export function visLen(s: string): number {
  let n = 0;
  for (const ch of s) {
    const code = ch.codePointAt(0) ?? 0;
    n += code > 0x2e80 ? 1 : ch === ' ' ? 0.3 : 0.58;
  }
  return n;
}

export function truncate(s: string, n: number): string {
  const chars = [...s];
  return chars.length > n ? chars.slice(0, n).join('') + '…' : s;
}
