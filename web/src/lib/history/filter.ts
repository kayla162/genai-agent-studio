import type { HistoryEntry, TemplateId } from '@/types/contract';

export interface HistoryFilters {
  brandId: string | 'all';
  templateId: TemplateId | 'all';
  /** YYYY-MM-DD（本地時間，含當天）；null 代表不限 */
  from: string | null;
  to: string | null;
  favoritesOnly: boolean;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** ISO 時間 → 本地日期 YYYY-MM-DD */
export function localDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 歷史紀錄篩選（品牌、通路、日期、收藏），最新的在前 */
export function filterHistory(entries: HistoryEntry[], f: HistoryFilters): HistoryEntry[] {
  return entries
    .filter((e) => f.brandId === 'all' || e.brandId === f.brandId)
    .filter((e) => f.templateId === 'all' || e.templateId === f.templateId)
    .filter((e) => !f.favoritesOnly || e.favorite)
    .filter((e) => {
      const day = localDate(e.selectedAt);
      return (!f.from || day >= f.from) && (!f.to || day <= f.to);
    })
    .sort((a, b) => b.selectedAt.localeCompare(a.selectedAt));
}
