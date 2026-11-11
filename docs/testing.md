# 测试

前端：在 `studybuddy-client` 运行 `npm test`、`npm run lint`、`npm run typecheck`、`npm run build`。已有微信组件测试显式启用集成；应用默认仍关闭，配置测试单独覆盖默认行为。

后端脚本校验需要 `ripgrep`（`rg`）；中文 PDF 用例还需要系统中文字体。Linux / Ubuntu 可先安装 `sudo apt-get update && sudo apt-get install -y ripgrep fonts-wqy-microhei`。该字体包提供现有 PDF fixture 检测的 `wqy-microhei.ttc`。其他系统请安装 `ripgrep` 和可用的中文字体；缺字体时 PDF 用例会跳过，`pytest -rs` 可显示实际跳过原因。

后端测试需要独立的本地 MySQL 测试库。先创建空库（名称必须以 `_test` 结尾），以该库的连接配置运行 `scripts/init_db.py`。测试入口拒绝远程地址、非测试库名和未显式授权的环境：

```bash
# 在 studybuddy-backend，使用你自己的隔离测试库连接参数。
export DB_HOST=127.0.0.1 DB_PORT=3307
export DB_USER=studybuddy DB_PASSWORD=your-local-test-password
export DB_NAME=studybuddy_oss_test
export JWT_SECRET=synthetic-local-test-jwt-secret
export STUDYBUDDY_TEST_DATABASE=1
# 旧微信测试验证启用场景，只使用假的适配器地址与 token。
export WECHAT_ENABLED=true
export WECHAT_BOT_SERVICE_URL=https://example.invalid/bot
export WECHAT_BOT_INTERNAL_TOKEN=synthetic-token
export WECHAT_PARENT_INVITATION_URL=https://example.invalid/invite
export WECHAT_OFFICIAL_ACCOUNT_QR_URL=https://example.invalid/qr
export WECHAT_ACCESS_TOKEN_URL=https://example.invalid/token
export WECHAT_CUSTOMER_MESSAGE_URL=https://example.invalid/message
PYTHONPATH=. .venv/bin/python scripts/init_db.py
PYTHONPATH=. .venv/bin/python -m pytest -q -rs -o addopts=''
```

默认测试清空模型密钥，使用合成 fixture 和模型替身，不证明模型教学效果。SSE 测试需要提交合成登录账号供独立连接访问，因此务必使用一次性测试库；测试完成后可删除自己创建的库。

真实体验可以使用完全虚构的分数运算场景：提出两个短任务的计划、确认草案、进入第一项、回答问题并检查证据记录、重新打开任务、把未完成项目沿用到今天。核对数据库结果与界面，不只检查 HTTP 状态。不要上传真实学生数据来演示。

真实模型调用、数据库版本、浏览器和 Docker 的验证范围以具体交付记录为准，不能用模拟结果替代。

## 微信 Bot、官网和 HobbyBuddy

Bot 必须使用独立虚拟环境（`hermes-agent` 的 `httpx` 等固定版本与主后端不同），不要合并两份 requirements 到同一环境：

```bash
# 仓库根目录
python3.11 -m venv wechat_bot_service/.venv
wechat_bot_service/.venv/bin/python -m pip install -r wechat_bot_service/requirements.txt pytest pytest-asyncio
wechat_bot_service/.venv/bin/python -m pytest wechat_bot_service/tests -q
```

Bot 测试使用本机 aiohttp 测试服务器和合成 iLink/账号适配器，不扫码、不读取个人 Hermes 凭据、不调用真实微信。

官网在 `studybuddy-client` 执行 `npm run build:landing`；产物独立于主应用。

HobbyBuddy 后端测试：仓库根目录设置 `PYTHONPATH=studybuddy-backend:hobbybuddy/backend`，使用后端测试依赖运行 `python -m pytest hobbybuddy/backend/tests -q`。数据库夹具是 SQLite 内存库，模型与资源搜索用替身。客户端在 `hobbybuddy/client` 执行 `npm ci`、`npm run lint`、`npm run typecheck`、`npm run build`，当前没有独立前端 test 脚本；`lint` 实际为 TypeScript 检查。

完整后端测试会收集 `tests/live/` 并默认跳过。只有明确授权真实模型、设定调用预算时才可以使用 `--run-live`；本次交付不运行它们。
