# 趣爱好前端（第一版最小化）

登录 + 对话两页，复用知了的技术栈（React + AntD + Vite）。

## 启动

```bash
cd client
npm install
npm run dev  # 默认 5173，VITE_API_BASE 指向 hobbybuddy 后端（http://127.0.0.1:8002）
```

## 页面

- `/` 登录/注册
- `/chat` 对话（SSE 预留，第一版 POST 轮询式简单对话）

> 第一版为最小跑通验证，UI 极简；完整体验（作品列表、进度、手机端）见功能文档演进。
