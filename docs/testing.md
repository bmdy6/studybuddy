# 测试

前端：在 `studybuddy-client` 运行 `npm test`、`npm run lint`、`npm run typecheck`、`npm run build`。已有微信组件测试显式启用集成；应用默认仍关闭，配置测试单独覆盖默认行为。

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
PYTHONPATH=. .venv/bin/python -m pytest -q -o addopts=''
```

默认测试清空模型密钥，使用合成 fixture 和模型替身，不证明模型教学效果。SSE 测试需要提交合成登录账号供独立连接访问，因此务必使用一次性测试库；测试完成后可删除自己创建的库。

真实体验可以使用完全虚构的分数运算场景：提出两个短任务的计划、确认草案、进入第一项、回答问题并检查证据记录、重新打开任务、把未完成项目沿用到今天。核对数据库结果与界面，不只检查 HTTP 状态。不要上传真实学生数据来演示。

真实模型调用、数据库版本、浏览器和 Docker 的验证范围以具体交付记录为准，不能用模拟结果替代。
