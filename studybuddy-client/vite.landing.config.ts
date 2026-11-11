import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { loadBrandConfig } from './tools/load-brand-config.mjs';

const brand = loadBrandConfig();

// 官网独立构建配置：产物 dist-landing/（与业务 SPA 的 dist/ 分离），静态资源独立 landing-public/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_BRAND__: JSON.stringify(brand),
  },
  base: './',
  publicDir: 'landing-public',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist-landing',
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'landing.html'),
    },
  },
});
