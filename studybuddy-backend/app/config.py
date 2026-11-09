import re
from datetime import time
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    """YAML 字符串列表 → tuple：校验非空字符串且无重复。

    agent 词表（试卷路由词/轻练触发词/守卫关键词等）统一走此转换，
    配置层保证数据合法，代码层直接消费。
    """
    if not isinstance(value, list):
        raise ValueError("必须是字符串列表")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("词表元素必须是非空字符串")
        items.append(item)
    if len(set(items)) != len(items):
        raise ValueError("词表元素不能重复")
    return tuple(items)


# 通用词表类型：YAML list → 非空无重复字符串 tuple
KeywordTuple = Annotated[tuple[str, ...], BeforeValidator(_as_string_tuple)]


def _as_subject_codes(value: Any) -> tuple[str, ...]:
    """科目代码：在词表校验基础上要求纯小写标识符（协议契约，新增科目需同步能力）。"""
    codes = _as_string_tuple(value)
    for code in codes:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
            raise ValueError(f"科目标识必须是纯小写标识符：{code}")
    return codes


SubjectCodes = Annotated[tuple[str, ...], BeforeValidator(_as_subject_codes)]

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _BACKEND_ROOT / "config.yaml"


class FrozenConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BrandConfig(FrozenConfigModel):
    name: str = Field(min_length=1, pattern=r".*\S.*")
    name_en: str = ""


class LlmConfig(FrozenConfigModel):
    provider: Literal["mimo", "openai"] = "mimo"
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(gt=0, le=600)
    retry_count: int = Field(ge=0, le=10)
    retry_backoff_base: float = Field(ge=1, le=10)
    circuit_fail_threshold: int = Field(gt=0, le=100)
    circuit_reset_seconds: int = Field(gt=0, le=3600)
    # MiMo 思考程度：none=关思考（thinking.type=disabled，最快）；空=默认开思考。
    # 注：mimo-v2.5 的 low/medium/high 实测不区分强度（都开思考），只有 none 有实际效果。
    reasoning_effort: str = Field(default="", pattern=r"^(none|low|medium|high)$")


class PracticeExamConfig(FrozenConfigModel):
    """正式试卷路由（create_practice_exam）意图关键词与科目代码。

    路由判定逻辑在 context.practice_exam_route_hint；正则组合（如"做一套卷子"）
    属算法结构留代码，这里只放运营词表数据。
    """

    route_keywords: KeywordTuple
    query_exclusion_keywords: KeywordTuple
    subject_codes: SubjectCodes


class LightPracticeConfig(FrozenConfigModel):
    """对话轻练（grade_light_answer）触发/退出词与题数边界。"""

    trigger_keywords: KeywordTuple
    exit_keywords: KeywordTuple
    min_questions: int = Field(gt=0)
    max_questions: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_question_range(self) -> "LightPracticeConfig":
        if self.min_questions > self.max_questions:
            raise ValueError("min_questions 不能大于 max_questions")
        return self


class AgentProfileConfig(FrozenConfigModel):
    """学习档案科目代码 → 展示标签映射（chinese/math/english/pe 等）。"""

    subject_labels: dict[str, str]

    @field_validator("subject_labels")
    @classmethod
    def _valid_subject_labels(cls, value: dict[str, str]) -> dict[str, str]:
        for code, label in value.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
                raise ValueError(f"科目标识必须是纯小写标识符：{code}")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"科目[{code}]的标签不能为空")
        return value


class PlanGuardConfig(FrozenConfigModel):
    """计划草案守卫：敏感轮触发词与目标/时长提问形状关键词。"""

    negotiation_keywords: KeywordTuple
    goal_question_hints: KeywordTuple


class TextbookGuardConfig(FrozenConfigModel):
    """教材诚实守卫：敏感轮触发词与证据/安全提示词。"""

    sensitive_keywords: KeywordTuple
    uncertainty_hints: KeywordTuple
    question_hints: KeywordTuple
    ocr_attribution_hints: KeywordTuple
    unconfirmed_safety_hints: KeywordTuple


class AgentConfig(FrozenConfigModel):
    tool_timeout_seconds: int = Field(gt=0, le=300)
    practice_exam: PracticeExamConfig
    light_practice: LightPracticeConfig
    profile: AgentProfileConfig
    plan_guard: PlanGuardConfig
    textbook_guard: TextbookGuardConfig


class AppConfig(FrozenConfigModel):
    log_level: str = Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")
    public_upload_base_path: str = Field(min_length=1)


class WechatConfig(FrozenConfigModel):
    bind_expire_seconds: int = Field(gt=0)
    customer_message_window_hours: int = Field(gt=0)
    timezone: str = Field(min_length=1)
    api_timeout_seconds: int = Field(gt=0, le=120)
    bot_api_timeout_seconds: int = Field(gt=0, le=120)
    bot_proactive_message_limit: int = Field(gt=0)
    guardian_push_time_options: tuple[str, ...] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("必须是有效 IANA 时区") from None
        return value

    @field_validator("guardian_default_push_time")
    @classmethod
    def _valid_push_time(cls, value: str) -> str:
        try:
            time.fromisoformat(value)
        except ValueError:
            raise ValueError("必须是有效 HH:MM 时间") from None
        return value

    @field_validator("guardian_push_time_options", mode="before")
    @classmethod
    def _tuple_from_yaml_list(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("必须是 YAML 列表")
        return tuple(value)
    guardian_default_push_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    growth_evidence_limit: int = Field(gt=0)
    growth_summary_max_tokens: int = Field(gt=0)
    daily_record_summary_max_tokens: int = Field(gt=0)


class ChatContextConfig(FrozenConfigModel):
    max_chars: int = Field(gt=0)
    recent_turns: int = Field(gt=0)
    summary_max_chars: int = Field(gt=0)
    message_max_chars: int = Field(gt=0)
    tool_max_chars: int = Field(gt=0)


class OfficialSourceSeed(FrozenConfigModel):
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    source_adapter: str = Field(min_length=1)
    url: str | None = None


class QuestionBankConfig(FrozenConfigModel):
    bili_search_page_size: int = Field(gt=0, le=100)
    bili_search_top_n: int = Field(gt=0, le=20)
    bili_search_timeout_seconds: int = Field(gt=0, le=120)
    search_timeout_seconds: int = Field(gt=0, le=120)
    review_timeout_seconds: int = Field(gt=0, le=120)
    official_source_site_seeds: dict[str, tuple[OfficialSourceSeed, ...]]

    @field_validator("official_source_site_seeds", mode="before")
    @classmethod
    def _seed_tuples_from_yaml_lists(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("必须是对象")
        normalized: dict[str, tuple[Any, ...]] = {}
        for location, seeds in value.items():
            if not isinstance(location, str) or not isinstance(seeds, list):
                raise ValueError("每个地区的来源必须是 YAML 列表")
            normalized[location] = tuple(seeds)
        return normalized


class BilibiliAssistConfig(FrozenConfigModel):
    """B站学习助手（bilibili_course_assist）配置：转写上限/CLI 路径/超时/并发。"""

    enabled: bool = True
    transcript_max_chars: int = Field(default=30000, gt=0)
    audio_max_seconds: int = Field(default=300, gt=0)
    api_timeout_seconds: int = Field(default=15, gt=0, le=60)
    transcribe_total_timeout_seconds: int = Field(default=40, gt=0, le=300)
    bili_cli_path: str = Field(default="bili", min_length=1)
    bili_cli_timeout_seconds: int = Field(default=180, gt=0, le=600)
    groq_timeout_seconds: int = Field(default=60, gt=0, le=120)
    groq_model: str = Field(default="whisper-large-v3", min_length=1)
    concurrent_segments: int = Field(default=4, gt=0, le=16)


class ConfigSettings(FrozenConfigModel):
    brand: BrandConfig
    llm: LlmConfig
    agent: AgentConfig
    app: AppConfig
    wechat: WechatConfig
    chat_context: ChatContextConfig
    question_bank: QuestionBankConfig
    bilibili_assist: BilibiliAssistConfig = BilibiliAssistConfig()


class SecretSettings(BaseSettings):
    DB_HOST: str
    DB_PORT: int = Field(default=3307, ge=1, le=65535)
    DB_USER: str
    DB_PASSWORD: SecretStr
    DB_NAME: str = "studybuddy_oss"

    COS_SECRET_ID: SecretStr = SecretStr("")
    COS_SECRET_KEY: SecretStr = SecretStr("")
    COS_BUCKET: str = ""
    COS_REGION: str = "ap-shanghai"

    JWT_SECRET: SecretStr = Field(min_length=16)
    JWT_EXPIRE_HOURS: int = Field(default=24, gt=0)
    JWT_REMEMBER_LOGIN_HOURS: int = Field(default=30 * 24, gt=0)

    APP_PORT: int = Field(default=8001, ge=1, le=65535)
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "*"
    LOG_DIR: str = ""

    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_BASE_URL: str = "https://api.xiaomimimo.com/v1"

    MARKDOWN_OCR_PROVIDER: str = "mimo"
    MARKDOWN_OCR_COMMAND: str = ""
    MARKDOWN_OCR_TIMEOUT_SEC: int = Field(default=12, gt=0)

    # B站学习助手音频转写（groq whisper）：密钥只用于请求头，不打印不落日志
    GROQ_API_KEY: SecretStr = SecretStr("")

    WECHAT_ENABLED: bool = False
    WECHAT_TOKEN: SecretStr = SecretStr("")
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: SecretStr = SecretStr("")
    WECHAT_OFFICIAL_ACCOUNT_QR_URL: str = ""
    WECHAT_ACCESS_TOKEN_URL: str = "https://api.weixin.qq.com/cgi-bin/token"
    WECHAT_CUSTOMER_MESSAGE_URL: str = "https://api.weixin.qq.com/cgi-bin/message/custom/send"
    WECHAT_BOT_SERVICE_URL: str = ""
    WECHAT_BOT_INTERNAL_TOKEN: SecretStr = SecretStr("")
    WECHAT_PARENT_INVITATION_URL: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _enabled_wechat_has_configuration(self) -> "SecretSettings":
        if self.WECHAT_ENABLED:
            required = {
                "WECHAT_BOT_SERVICE_URL": self.WECHAT_BOT_SERVICE_URL,
                "WECHAT_BOT_INTERNAL_TOKEN": self.WECHAT_BOT_INTERNAL_TOKEN.get_secret_value(),
                "WECHAT_PARENT_INVITATION_URL": self.WECHAT_PARENT_INVITATION_URL,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError("WeChat enabled but missing: " + ", ".join(missing))
        return self


class Settings:
    """应用唯一配置入口；兼容旧平铺属性，新增配置优先走嵌套对象。"""

    def __init__(self, config: ConfigSettings, secrets: SecretSettings):
        self.config = config
        self.secrets = secrets

    def __getattr__(self, name: str) -> Any:
        compatibility_values = {
            "BRAND_NAME": self.config.brand.name,
            "LLM_MODEL": self.config.llm.model,
            "LLM_TIMEOUT_SEC": self.config.llm.timeout_seconds,
            "LLM_REASONING_EFFORT": self.config.llm.reasoning_effort,
            "LOG_LEVEL": self.config.app.log_level,
            "PUBLIC_UPLOAD_BASE_PATH": self.config.app.public_upload_base_path,
            "WECHAT_BIND_EXPIRE_SECONDS": self.config.wechat.bind_expire_seconds,
            "WECHAT_CUSTOMER_MESSAGE_WINDOW_HOURS": self.config.wechat.customer_message_window_hours,
            "WECHAT_TIMEZONE": self.config.wechat.timezone,
            "WECHAT_API_TIMEOUT_SECONDS": self.config.wechat.api_timeout_seconds,
            "WECHAT_BOT_API_TIMEOUT_SECONDS": self.config.wechat.bot_api_timeout_seconds,
            "WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT": self.config.wechat.bot_proactive_message_limit,
            "WECHAT_GUARDIAN_PUSH_TIME_OPTIONS": ",".join(self.config.wechat.guardian_push_time_options),
            "WECHAT_GUARDIAN_DEFAULT_PUSH_TIME": self.config.wechat.guardian_default_push_time,
            "WECHAT_GROWTH_EVIDENCE_LIMIT": self.config.wechat.growth_evidence_limit,
            "WECHAT_GROWTH_SUMMARY_MAX_TOKENS": self.config.wechat.growth_summary_max_tokens,
            "DAILY_RECORD_SUMMARY_MAX_TOKENS": self.config.wechat.daily_record_summary_max_tokens,
            "CHAT_CONTEXT_MAX_CHARS": self.config.chat_context.max_chars,
            "CHAT_CONTEXT_RECENT_TURNS": self.config.chat_context.recent_turns,
            "CHAT_CONTEXT_SUMMARY_MAX_CHARS": self.config.chat_context.summary_max_chars,
            "CHAT_CONTEXT_MESSAGE_MAX_CHARS": self.config.chat_context.message_max_chars,
            "CHAT_CONTEXT_TOOL_MAX_CHARS": self.config.chat_context.tool_max_chars,
        }
        if name in compatibility_values:
            return compatibility_values[name]
        return getattr(self.secrets, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"config", "secrets"}:
            object.__setattr__(self, name, value)
            return
        if hasattr(self.secrets, name):
            setattr(self.secrets, name, value)
            return
        object.__setattr__(self, name, value)


def _format_validation_error(exc: ValidationError) -> str:
    errors = []
    for error in exc.errors(include_url=False, include_input=False):
        path = ".".join(str(part) for part in error["loc"])
        errors.append(f"{path}: {error['msg']}")
    return "; ".join(errors)


def load_config_settings(path: Path = _CONFIG_PATH) -> ConfigSettings:
    if not path.is_file():
        raise RuntimeError(f"配置文件不存在：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("配置文件根节点必须是对象")
        return ConfigSettings.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"配置文件校验失败：{_format_validation_error(exc)}") from None
    except yaml.YAMLError:
        raise ValueError("配置文件 YAML 格式错误") from None


def reveal_secret(value: SecretStr | str) -> str:
    """仅供基础设施适配边界解包；兼容测试临时替换的普通字符串。"""
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def has_secret(value: SecretStr | str) -> bool:
    return bool(reveal_secret(value))


def load_secret_settings() -> SecretSettings:
    try:
        return SecretSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors(include_url=False, include_input=False)})
        raise RuntimeError(f"环境变量配置校验失败：{', '.join(fields)}") from None


settings = Settings(load_config_settings(), load_secret_settings())
