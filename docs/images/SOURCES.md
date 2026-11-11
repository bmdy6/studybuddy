# 截图来源与复现

本次所有应用截图都由真实 React → FastAPI → 独立 MySQL 8.4 页面生成。种子只有手写的虚构计划、对话、作答、判定和回顾，不调用模型；草案与已有任务是两个独立 fixture，不能把预填对话当作本次模型教学结果。

- `overview.png`：桌面学习页，1440×900。
- `plan-confirm.png`：桌面聊天页中的两项计划草案，1280×800。
- `task-session.png`：桌面任务对话与作答，1280×800。
- `resume.png`：计划管理页，1280×800。
- `mobile-task.png`、`mobile-plan.png`、`mobile-notes.png`：手机端真实页面，390×844。
- `wechat-daily-demo.png`：**微信聊天示意**；`build_parent_daily_summary` 从虚构家长与学生关系、计划和每日回顾生成正文，Playwright 将文本渲染为气泡。不是微信实际投递截图。
- `landing.png`：本次恢复的官网真实页面，1440px；Hero 中三张图同样来自上述合成数据手机页面。

`capture-receipt.json` 记录 Chromium 版本、应用路由、视口和图片 SHA-256。`illustrate.json` 是本次文件清单，替换旧的 README 插图块说明。

## 复现

新建一次性 MySQL 实例和空库 `readme_demo_test`，专用本机端口及账号。不要使用任何已有个人或生产数据库。

1. 按根 README 安装主后端与客户端依赖。
2. 在后端导出 `DB_HOST=127.0.0.1`、独立 `DB_PORT/DB_USER/DB_PASSWORD`、`DB_NAME=readme_demo_test`、合成 `JWT_SECRET`、`WECHAT_ENABLED=false`、空 `LLM_API_KEY`、`LLM_BASE_URL=http://127.0.0.1:9`、`CORS_ORIGINS=http://127.0.0.1:15183`。
3. 在后端运行 `PYTHONPATH=. .venv/bin/python scripts/init_db.py`，然后 `PYTHONPATH=. .venv/bin/python ../docs/images/seed-demo.py`。脚本拒绝非指定本机数据库与已有用户。
4. 后端启动在 `127.0.0.1:18083`；客户端设置 `VITE_API_BASE=http://127.0.0.1:18083`，启动在 `127.0.0.1:15183`。
5. 仓库根目录执行 `node docs/images/capture-demo.mjs`，使用 headless Chromium。必要时先在客户端目录执行 `npx playwright install chromium`。
6. 官网设置 `VITE_APP_URL=http://127.0.0.1:15183` 并启动在 `127.0.0.1:15184`；执行 `node docs/images/smoke-demo.mjs` 验证 UI 确认计划、导航后持久化、手机端任务刷新、微信关闭时主流程，以及官网四个断点。这一步会消费种子草案，重新执行需重建**自己的一次性演示库**。

生成的 `*-state.private.json` 含合成账号登录 token，已被忽略，不提交。完成后停止本次服务并销毁临时 MySQL。原 landing-public 的旧截图和二维码均未搬，官网引用本次新截图副本。
