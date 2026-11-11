"""pytest 全局配置：测试环境不依赖本地 .env。"""

import os

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3307")
os.environ.setdefault("DB_USER", "studybuddy")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "hobbybuddy_test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest-only-0123456789")
# 底座 app.config 校验需要这些字段（兴趣空间用不到，占位即可）
os.environ.setdefault("WECHAT_ACCESS_TOKEN_URL", "https://example.com/token")
os.environ.setdefault("WECHAT_BOT_INTERNAL_TOKEN", "placeholder")
os.environ.setdefault("WECHAT_BOT_SERVICE_URL", "https://example.com/bot")
os.environ.setdefault("WECHAT_CUSTOMER_MESSAGE_URL", "https://example.com/msg")
os.environ.setdefault("WECHAT_OFFICIAL_ACCOUNT_QR_URL", "https://example.com/qr.jpg")
os.environ.setdefault("WECHAT_PARENT_INVITATION_URL", "https://example.com/invite")
# 底座 LLM 配置
os.environ.setdefault("LLM_API_KEY", "test-key")
