import { defineConfig, devices } from '@playwright/test';

// 自制接口夹具只验证前端交互，不计作真实 API / Worker 联调。
export default defineConfig({
  testDir: './tests', testMatch: '*.frontend.spec.ts', timeout: 30000,
  expect: { timeout: 8000 }, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: { command: 'pnpm dev', url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.CI },
});
