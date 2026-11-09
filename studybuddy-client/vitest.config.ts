/// <reference types="vitest" />
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { loadBrandConfig } from './tools/load-brand-config.mjs';

const brand = loadBrandConfig();

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_BRAND__: JSON.stringify(brand),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    // Existing channel tests exercise the configured integration. Production
    // stays disabled by default; integrationSettings.test.ts covers that default.
    env: { VITE_WECHAT_ENABLED: 'true' },
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.tsx',
    css: false,
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/playwright-report/**'],
  },
});
