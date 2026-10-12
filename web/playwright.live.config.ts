import { defineConfig, devices } from '@playwright/test';
import { E2E_URL } from './e2e-live/stack';

/**
 * live 模式 E2E：以 docker compose 啟動獨立的整套服務（外部服務用模擬版，1× 速度約 16 秒一個任務），測完移除。
 * 後端一次只執行一個生圖任務，所以測試依序執行。需要 Docker；npm run e2e:live
 */
export default defineConfig({
  testDir: './e2e-live',
  timeout: 120_000,
  expect: { timeout: 45_000 },
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  globalSetup: './e2e-live/global-setup.ts',
  globalTeardown: './e2e-live/global-teardown.ts',
  use: {
    baseURL: E2E_URL,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
