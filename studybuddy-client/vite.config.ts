import path from 'node:path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { loadBrandConfig } from './tools/load-brand-config.mjs';

const brand = loadBrandConfig();

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
  plugins: [react()],
  define: {
    __APP_BRAND__: JSON.stringify(brand),
  },
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // 素材本地存储走后端 StaticFiles（/uploads），开发时代理到后端，避免被 SPA fallback 吞掉
    proxy: {
      '/uploads': {
        target: env.VITE_API_BASE || 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom', 'zustand'],
          antd: ['antd', '@ant-design/icons'],
          charts: ['recharts'],
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
  };
});
