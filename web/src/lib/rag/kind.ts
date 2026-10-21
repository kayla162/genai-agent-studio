/** 由 id 看出的切塊類型（品牌知識庫以標籤標示）；一般的 CI 規範切塊沒有類型 */
export type ChunkKind = 'upload' | 'history' | 'case' | 'alt';

export const CHUNK_KIND_LABEL: Record<ChunkKind, string> = {
  upload: '新上傳', history: '歷史回寫', case: '歷史案例', alt: 'Query Rewriting 專用',
};

export function chunkKind(id: string): ChunkKind | null {
  if (id.includes('#doc-')) return 'upload';
  if (id.includes('#hist-')) return 'history';
  if (id.includes('#case-')) return 'case';
  if (id.endsWith('-alt')) return 'alt';
  return null;
}
