import { expect, test, type Page } from '@playwright/test';

async function seed(page: Page) {
  await page.goto('/dashboard');
  await expect(page.getByText('還沒有已結束的任務')).toBeVisible();
  await page.getByRole('button', { name: '產生 12 個示範任務' }).click();
  await expect(page.getByText('各檢查項失敗分布', { exact: true })).toBeVisible();
}

test('成效儀表板：示範任務的 KPI、圖表與最近任務，並可點進 Agent 透視', async ({ page }) => {
  await seed(page);
  await expect(page.getByText('共 6 個任務')).toBeVisible();
  await expect(page.getByText(/Top 3：\d+% → 100%/)).toBeVisible();
  await expect(page.locator('[data-chart] svg').first()).toBeVisible();

  await page.getByRole('combobox', { name: '統計範圍' }).click();
  await page.getByRole('option', { name: '全部品牌' }).click();
  await expect(page.getByText('共 12 個任務')).toBeVisible();
  await expect(page.getByText('需人工審核').first()).toBeVisible();

  await page.getByRole('link', { name: /^job_/ }).first().click();
  await expect(page).toHaveURL(/\/agent\?job=job_/);
  await expect(page.getByText('流程節點', { exact: true })).toBeVisible();
  await expect(page.getByText(/\d+ 則事件/)).toBeVisible();
});

test('手機寬度（375px）的 Agent 透視與儀表板沒有水平捲軸', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await seed(page);
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(await overflow()).toBeLessThanOrEqual(0);
  await page.goto('/agent');
  await expect(page.getByText('流程節點', { exact: true })).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(0);
});
