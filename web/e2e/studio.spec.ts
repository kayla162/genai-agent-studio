import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import JSZip from 'jszip';

test('一句話需求 → 生成 → 第一輪失敗並重試 → 選圖 → 改價格 → 匯出 zip → Agent 透視看重試 diff', async ({ page }) => {
  await page.goto('/studio');

  // Demo 控制台：4× 播放（預設強制首輪失敗）
  await page.getByRole('button', { name: '開啟 Demo 控制台' }).click();
  await page.getByRole('radio', { name: '4×' }).click();
  await page.keyboard.press('Escape');

  // 一句話需求 → Agent 拆解
  await page.getByLabel('一句話需求').fill('幫我做週年慶的精華液海報，主打買一送一，要溫柔療癒的感覺');
  await page.getByRole('button', { name: 'Agent 拆解需求' }).click();
  await expect(page.getByLabel('檔期')).toHaveValue('週年慶');
  await expect(page.getByLabel('優惠')).toHaveValue('買一送一');

  // 只留 IG 貼文
  await page.getByRole('checkbox', { name: '電商主圖' }).click();
  await expect(page.getByRole('checkbox', { name: 'IG 貼文' })).toBeChecked();
  await page.getByRole('button', { name: /開始生成（1 個模板/ }).click();

  // 第一輪未通過 → Query Rewriting → 第二輪通過
  await expect(page.getByText('第 1 輪未通過審查，Query Rewriting 後重試')).toBeVisible();
  await expect(page.getByText('文字編輯器', { exact: true })).toBeVisible();
  await expect(page.getByText('已重試')).toBeVisible();

  // 選另一張候選，再改價格
  await page.getByRole('button', { name: '選用', exact: true }).first().click();
  await page.getByLabel('特價').fill('999');
  await expect(page.getByLabel('特價')).toHaveValue('999');

  // 匯出 zip：檢查下載事件與 zip 內容
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: /匯出 zip 並寫入歷史（1 張）/ }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^SÉLUNE晞月_極光玻尿酸修護精華30ml_\d{8}\.zip$/);
  const zip = await JSZip.loadAsync(await readFile(await download.path()));
  const names = Object.keys(zip.files);
  expect(names).toHaveLength(1);
  expect(names[0]).toMatch(/^SÉLUNE晞月_極光玻尿酸修護精華30ml_IG貼文_\d{8}\.png$/);
  const png = await zip.file(names[0])!.async('uint8array');
  // PNG 檔頭與 IHDR 中的寬高（IG 貼文 1440×1800）
  expect([...png.slice(1, 4)].map((c) => String.fromCharCode(c)).join('')).toBe('PNG');
  const view = new DataView(png.buffer, png.byteOffset);
  expect([view.getUint32(16), view.getUint32(20)]).toEqual([1440, 1800]);
  await expect(page.getByText('已匯出 1 張海報')).toBeVisible();

  // Agent 透視：重試 diff 顯示改寫前後的主色
  await page.getByRole('link', { name: '在 Agent 透視查看細節' }).click();
  await expect(page).toHaveURL(/\/agent\?job=job_/);
  await page.getByRole('tab', { name: /重試 diff/ }).click();
  const diff = page.getByRole('row', { name: /palette\.primary/ });
  await expect(diff).toContainText('#E0458A');
  await expect(diff).toContainText('#B76E79');
  await expect(page.getByText('第 1 輪 → 第 2 輪・IG 貼文')).toBeVisible();
});
