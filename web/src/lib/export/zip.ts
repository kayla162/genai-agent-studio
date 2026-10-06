import JSZip from 'jszip';

export interface ZipEntry { name: string; data: Blob | Uint8Array }

/** 檔名重複時在副檔名前加上 (2)、(3)… */
export function uniqueName(name: string, used: Set<string>): string {
  const dot = name.lastIndexOf('.');
  const [base, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ''];
  let candidate = name;
  for (let i = 2; used.has(candidate); i++) candidate = `${base} (${i})${ext}`;
  used.add(candidate);
  return candidate;
}

/** 打包成 zip。Blob 先轉成位元組（JSZip 讀 Blob 需要 FileReader，Node 測試環境沒有）。 */
export async function buildZip(entries: ZipEntry[]): Promise<Blob> {
  const zip = new JSZip();
  const used = new Set<string>();
  for (const e of entries) {
    const bytes = e.data instanceof Uint8Array ? e.data : new Uint8Array(await e.data.arrayBuffer());
    zip.file(uniqueName(e.name, used), bytes);
  }
  return zip.generateAsync({ type: 'blob', mimeType: 'application/zip' });
}
