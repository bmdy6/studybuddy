"""hobbybuddy 配置：读自己的 config.yaml + .env。

模仿 studybuddy-backend/app/config.py，但独立 config.yaml（品牌：趣爱好）与独立 .env
（DB_NAME=hobbybuddy、独立 JWT_SECRET）。LLM 配置复用底座同名模型账号。

不 import 底座 config（品牌名、DB 连接都要独立）；底座 ai_service 内部自带
settings，其 LLM 密钥从底座 .env 读取，两应用共用同一 MiMo 账号。
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _BACKEND_ROOT / "config.yaml"


class FrozenConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandConfig(FrozenConfigModel):
    name: str
    name_en: str = ""


class LlmConfig(FrozenConfigModel):
    model: str
    timeout_seconds: int
    retry_count: int
    retry_backoff_base: float
    circuit_fail_threshold: int
    circuit_reset_seconds: int
    reasoning_effort: str = ""


class AgentConfig(FrozenConfigModel):
    tool_timeout_seconds: int = 8


class AppConfig(FrozenConfigModel):
    log_level: str = "INFO"
    public_upload_base_path: str = "/uploads"


class ConfigSettings(FrozenConfigModel):
    brand: BrandConfig
    llm: LlmConfig
    agent: AgentConfig
    app: AppConfig


class SecretSettings(BaseSettings):
    DB_HOST: str
    DB_PORT: int = 3307
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str = "hobbybuddy"

    JWT_SECRET: str
    JWT_EXPIRE_HOURS: int = 24
    JWT_REMEMBER_LOGIN_HOURS: int = 720

    APP_PORT: int = 8002
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "*"

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.xiaomimimo.com/v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings:
    """hobbybuddy 配置入口。"""

    def __init__(self, config: ConfigSettings, secrets: SecretSettings):
        self.config = config
        self.secrets = secrets

    def __getattr__(self, name: str) -> str | int:
        compat = {
            "BRAND_NAME": self.config.brand.name,
            "LLM_MODEL": self.config.llm.model,
            "LLM_TIMEOUT_SEC": self.config.llm.timeout_seconds,
            "LLM_REASONING_EFFORT": self.config.llm.reasoning_effort,
            "LOG_LEVEL": self.config.app.log_level,
            "PUBLIC_UPLOAD_BASE_PATH": self.config.app.public_upload_base_path,
        }
        if name in compat:
            return compat[name]
        return getattr(self.secrets, name)


def _load_config(path: Path = _CONFIG_PATH) -> ConfigSettings:
    if not path.is_file():
        raise RuntimeError(f"配置文件不存在：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ConfigSettings.model_validate(raw)


settings = Settings(_load_config(), SecretSettings())
