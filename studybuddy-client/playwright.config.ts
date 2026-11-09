import { defineConfig } from '@playwright/test';

// M4 机器验收：设置 PLAYWRIGHT_BASE_URL 时指向外部已部署地址并禁用本地 webServer；
// 未设置时保持本地 5174 dev server 行为。
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 1,
  use: {
    baseURL: externalBaseUrl || 'http://localhost:5174',
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: 'npm run dev -- --port 5174',
        port: 5174,
        reuseExistingServer: true,
        timeout: 30000,
      },
});
