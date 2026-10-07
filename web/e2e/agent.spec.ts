import { expect, test } from '@playwright/test';

// 兩個測試都用 1× 速度（一筆任務約 15 秒），確保打開 Agent 透視時任務還在執行

test('任務選單：執行中打開的任務，完成後也顯示「完成」', async ({ page }) => {
  await page.goto('/studio');
  await page.getByRole('checkbox', { name: '電商主圖' }).click();
  await page.getByRole('button', { name: /開始生成（1 個模板/ }).click();
  await page.getByRole('link', { name: '在 Agent 透視查看細節' }).click();
  await expect(page).toHaveURL(/\/agent\?job=job_/);

  const picker = page.getByRole('combobox', { name: '選擇任務' });
  const saving = page.getByRole('listitem').filter({ hasText: '寫入 DB 與回傳' });
  await expect(saving).toContainText('未開始');
  await expect(picker).not.toContainText('完成');

  await expect(saving).toContainText('完成', { timeout: 30_000 });
  await expect(picker).toContainText('完成');
});

test('任務選單：打開時重新讀取，列出之後才開始的任務，但不換掉正在看的任務', async ({ page }) => {
  // 批次佇列一次執行一筆：第一筆完成後才啟動第二筆
  await page.goto('/queue');
  for (let i = 0; i < 2; i++) {
    await page.getByRole('checkbox', { name: '極光玻尿酸修護精華 30ml' }).click();
    await page.getByRole('button', { name: /加入佇列（1 筆任務/ }).click();
  }
  await expect(page.getByText('執行中')).toBeVisible();

  // 站內切換頁面，佇列在背景繼續執行；網址沒有指定任務，預設顯示最新的（第一筆）
  await page.getByRole('link', { name: 'Agent 透視' }).click();
  const picker = page.getByRole('combobox', { name: '選擇任務' });
  const saving = page.getByRole('listitem').filter({ hasText: '寫入 DB 與回傳' });
  await expect(saving).toContainText('未開始');
  const first = (await picker.textContent())!.match(/job_\w+/)![0];
  await expect(saving).toContainText('完成', { timeout: 30_000 });

  await picker.click();
  await expect(page.getByRole('option')).toHaveCount(2);
  await page.keyboard.press('Escape');
  await expect(picker).toContainText(first);
  await expect(saving).toContainText('完成');
});
