/** 瀏覽器端：上傳前把商品照縮到最長邊 maxSide，減少 IndexedDB 與海報繪製的負擔 */
export async function downscaleImage(file: Blob, maxSide = 1600): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size <= 1_500_000) {
    bitmap.close();
    return file;
  }
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  // PNG 保留透明背景；其他格式轉 JPEG
  const type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('圖片壓縮失敗'))), type, 0.9),
  );
}

/** 「night_mask-50ml.png」→「night mask 50ml」 */
export const nameFromFile = (fileName: string) => fileName.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim() || '未命名商品';
