import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BACKEND_PORT = 8811;
const FRONTEND_PORT = 4311;
const FRONTEND_ORIGIN = `http://127.0.0.1:${FRONTEND_PORT}`;

// Resolve the repo's own venv Python so the test backend has fastapi/uvicorn
// installed without depending on whatever `python` resolves to on PATH.
// PLAYWRIGHT_PYTHON_BIN overrides this (used by CI, where the venv is
// created by actions/setup-python rather than the Windows dev workflow).
const PYTHON =
  process.env.PLAYWRIGHT_PYTHON_BIN ??
  path.resolve(
    __dirname,
    process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python',
  );
const BACKEND_SCRIPT = path.resolve(__dirname, 'e2e/fixtures/test_backend.py');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // one shared backend/registry per run; keep tests serial and predictable
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  use: {
    baseURL: FRONTEND_ORIGIN,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: `"${PYTHON}" "${BACKEND_SCRIPT}"`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {
        E2E_BACKEND_PORT: String(BACKEND_PORT),
        E2E_FRONTEND_ORIGIN: FRONTEND_ORIGIN,
      },
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: FRONTEND_ORIGIN,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {
        VITE_API_TARGET: `http://127.0.0.1:${BACKEND_PORT}`,
      },
    },
  ],
});
