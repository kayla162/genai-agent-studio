import { expect, test, type Page } from '@playwright/test';
import { compose } from './stack';

// 對 docker compose 啟動的整套服務測試：任務由 worker 執行，事件經 nginx 的 WebSocket 送到前端

/** 只留 IG 貼文（1 個模板 × 2 張）開始生成；回傳任務 id */
async function startJob(page: Page): Promise<string> {
  await page.goto('/studio');
  await page.getByRole('checkbox', { name: '電商主圖' }).click();
  await expect(page.getByRole('checkbox', { name: 'IG 貼文' })).toBeChecked();
  await page.getByRole('button', { name: '開始生成（1 個模板 × 2 張）' }).click();
  const id = page.getByText(/^job_\d{8}_\d{4}_[0-9a-f]{4}$/);
  await expect(id).toBeVisible();
  return (await id.textContent())!;
}

async function job(page: Page, jobId: string) {
  return (await page.request.get(`/api/jobs/${jobId}`)).json();
}

const roundOne = (page: Page) => page.getByText('第 1 輪', { exact: true }).first();
const editor = (page: Page) => page.getByText('文字編輯器', { exact: true });

test('一句話需求 → 後端生成（第一輪失敗、重試後通過）→ 匯出並寫入歷史 → Agent 透視與儀表板', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(editor(page)).toBeVisible();

  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: '匯出 zip 並寫入歷史（1 張）' }).click();
  await downloading;
  await expect(page.getByText('已匯出 1 張海報')).toBeVisible();
  const history = await (await page.request.get('/api/history?brandId=selune')).json();
  expect(history[0]).toMatchObject({ jobId, templateId: 'ig-post', writtenToRag: true });
  await page.goto('/history');
  await expect(page.getByText('已回寫 RAG').first()).toBeVisible();

  const { events } = await job(page, jobId);
  await page.goto(`/agent?job=${jobId}`);
  await expect(page.getByText(`${events.length} 則事件`)).toBeVisible();
  await page.goto('/dashboard');
  await expect(page.getByText(jobId)).toBeVisible();
});

test('重新整理後接續執行中的任務', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  expect((await job(page, jobId)).summary.finished).toBe(false);
  await page.reload();
  await expect(page.getByText(jobId)).toBeVisible();
  await expect(editor(page)).toBeVisible();
  await expect(page.getByRole('button', { name: '匯出 zip 並寫入歷史（1 張）' })).toBeEnabled();
});

test('API 重新啟動時自動重新連線，補上中斷期間的事件', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  // 任務在 worker 繼續執行；api 重新啟動期間的事件由重新連線時從資料庫補送
  compose('restart', 'api');
  await expect(editor(page)).toBeVisible();
  expect((await job(page, jobId)).summary).toMatchObject({ stage: 'done', finished: true });
  await expect(page.getByRole('button', { name: '系統狀態' })).toContainText('WebSocket 已連線');
});

test('取消執行中的任務', async ({ page }) => {
  const jobId = await startJob(page);
  await expect(roundOne(page)).toBeVisible();
  await page.getByRole('button', { name: '取消任務' }).click();
  await expect(page.getByText('任務已取消。')).toBeVisible();
  expect((await job(page, jobId)).summary).toMatchObject({ stage: 'cancelled', finished: true });
});

test('上傳品牌文件：切塊 → 向量化 → 寫入，知識庫列出新的切塊', async ({ page }) => {
  await page.goto('/brands');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'e2e_ci.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# 色彩更新\n主色維持 #2F4A44。\n\n# Logo\n- 深色背景使用反白 Logo'),
  });
  await expect(page.getByText('collection「selune_ci」新增 2 筆')).toBeVisible();
  const brands: { id: string; guidelineChunks: { source: string }[] }[] = await (await page.request.get('/api/brands')).json();
  const selune = brands.find((b) => b.id === 'selune')!;
  expect(selune.guidelineChunks.filter((c) => c.source === 'e2e_ci.md')).toHaveLength(2);
});

test('上傳商品照到後端並建立商品', async ({ page }) => {
  await page.goto('/products');
  const png = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 60;
    canvas.height = 90;
    const g = canvas.getContext('2d')!;
    g.fillStyle = '#c9a27e';
    g.fillRect(15, 10, 30, 70);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'e2e_cream.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64'),
  });
  await expect(page.getByText('照片已上傳到後端（data/uploads/）。請補上價格與特徵。')).toBeVisible();
  const products: { photo: { source: string; url?: string } }[] = await (await page.request.get('/api/products?brandId=selune')).json();
  const url = products.find((p) => p.photo.source === 'upload')!.photo.url!;
  expect(url).toMatch(/^\/files\/uploads\/[0-9a-f]{16}\.(png|jpg|webp)$/);
  const img = page.locator(`img[src="${url}"]`).first();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
});
