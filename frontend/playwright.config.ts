import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  workers: process.env.CI ? 1 : 2,
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    // Linux Firefox needs a display for WebGL2; CI supplies Xvfb.
    { name: 'firefox', use: { browserName: 'firefox', headless: !(process.env.CI && process.platform === 'linux') } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
