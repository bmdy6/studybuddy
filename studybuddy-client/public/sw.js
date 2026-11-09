// 知了 PWA service worker
// 仅用于满足 PWA 安装条件（需有 fetch handler），不缓存业务内容。
// 原因：平台采用覆盖式部署，若 SW 缓存 index.html 会卡留旧版本；
// 平台需联网使用 LLM/API，无离线需求，故让所有请求直接走网络。
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', () => {
  // 不拦截，默认走网络
});
