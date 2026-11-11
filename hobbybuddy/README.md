# 趣爱好（HobbyBuddy）

独立账号、数据库和提示词的兴趣资源对话应用。复用 `studybuddy-backend` 的模型服务与 B 站资源搜索，不打分、不创建学科试卷。

## 本地运行

先按根 README 安装底座后端依赖；在 `hobbybuddy/backend` 复制 `.env.example` 为 `.env`，配置**新的独立数据库**、JWT 和自己的模型 key。模型配置在本目录 `config.yaml`，不读取其他项目的凭据。

```bash
# 从仓库根目录，安装 HobbyBuddy 的额外依赖
studybuddy-backend/.venv/bin/python -m pip install -r hobbybuddy/backend/requirements.txt
cd hobbybuddy/backend
# 数据库须自行新建；历史 DDL 只用于这个独立库
PYTHONPATH=../../studybuddy-backend ../../studybuddy-backend/.venv/bin/python scripts/run_ddl.py
PYTHONPATH=../../studybuddy-backend ../../studybuddy-backend/.venv/bin/uvicorn hobby.main:app --host 127.0.0.1 --port 8002
```

另开终端，在 `hobbybuddy/client` 执行 `npm ci`、`cp .env.example .env.local`、`npm run dev`。主 StudyBuddy 应用不依赖这个可选应用。

验证：`cd hobbybuddy/backend && PYTHONPATH=../../studybuddy-backend ../../studybuddy-backend/.venv/bin/python -m pytest -q`；其数据库测试使用 SQLite 内存替身，模型和搜索使用 mock。
