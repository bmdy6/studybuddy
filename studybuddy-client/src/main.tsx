import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App as AntdApp } from 'antd';
import { appleTheme } from '@/shared/theme/antdTheme';
import App from './App';
import { logger } from '@/shared/utils/logger';
import { BRAND } from '@/shared/constants';
import './index.css';

document.title = BRAND.name;

// 全局错误捕获：未捕获异常 + Promise 拒绝，便于排查生产白屏/卡死
window.addEventListener('error', (e) => {
  logger.error('global', e.message, { filename: e.filename, lineno: e.lineno, error: e.error });
});
window.addEventListener('unhandledrejection', (e) => {
  logger.error('promise', 'Unhandled rejection', e.reason);
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider theme={appleTheme} locale={undefined}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);

// 注册 PWA service worker（仅生产环境，满足「添加到主屏幕」安装条件）
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch((error) => {
      console.warn('SW 注册失败（不影响使用）:', error);
    });
  });
}
