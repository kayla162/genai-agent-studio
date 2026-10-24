import type { RagChunk } from '@/types/contract';

/** 一份上傳的手冊：檔名與切塊數 */
export interface UploadedDocument { source: string; chunks: number }

/** 上傳的手冊切塊的 id 是 {品牌}#doc-…（品牌設定檔的規範、歷史回寫與歷史案例不是） */
const isUploaded = (c: RagChunk) => c.id.includes('#doc-');

/** 依檔名分組，順序為第一次出現的順序（與知識庫列出切塊的順序相同） */
export function uploadedDocuments(chunks: RagChunk[]): UploadedDocument[] {
  const counts = new Map<string, number>();
  for (const c of chunks) if (isUploaded(c)) counts.set(c.source, (counts.get(c.source) ?? 0) + 1);
  return [...counts].map(([source, n]) => ({ source, chunks: n }));
}
