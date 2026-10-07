import { defineConfig, devices } from '@playwright/test';

const PORT = 3100;

/**
 * E2E：先建置正式版，再在 3100 埠啟動（不佔用 next dev 的 3000 埠）。
 * 每個測試都是新的瀏覽器 context，IndexedDB 與 localStorage 從空的開始。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && npm run start -- --port ${PORT}`,
    url: `http://localhost:${PORT}/studio`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
