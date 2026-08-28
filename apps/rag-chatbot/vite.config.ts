import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import path from 'node:path';

// The dev server proxies /api to the local FastAPI backend so the browser
// sees a single origin during development. The backend also allows this
// origin explicitly via CORS, so either path works.
const BACKEND = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Playwright owns e2e/; vitest must not try to run those specs.
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**'],
  },
});
