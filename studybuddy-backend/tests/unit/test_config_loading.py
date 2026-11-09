from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.config import ConfigSettings, SecretSettings, load_config_settings, load_secret_settings


VALID_CONFIG = """
brand:
  name: 知了
  name_en: ""
llm:
  model: mimo-v2.5
  timeout_seconds: 60
  retry_count: 2
  retry_backoff_base: 1.5
  circuit_fail_threshold: 5
  circuit_reset_seconds: 120
agent:
  tool_timeout_seconds: 8
  practice_exam:
    route_keywords: ["卷子", "试卷"]
    query_exclusion_keywords: ["看看", "之前"]
    subject_codes: ["math", "english", "chinese"]
  light_practice:
    trigger_keywords: ["练几道", "考我一道"]
    exit_keywords: ["卷子", "结束"]
    min_questions: 1
    max_questions: 3
  profile:
    subject_labels:
      chinese: "语文"
      math: "数学"
  plan_guard:
    negotiation_keywords: ["计划", "草案"]
    goal_question_hints: ["具体目标", "多久"]
  textbook_guard:
    sensitive_keywords: ["课本", "教材"]
    uncertainty_hints: ["无法确认", "不确定"]
    question_hints: ["？", "是否"]
    ocr_attribution_hints: ["根据你上传"]
    unconfirmed_safety_hints: ["可能", "请核对"]
app:
  log_level: INFO
  public_upload_base_path: /uploads
wechat:
  bind_expire_seconds: 180
  customer_message_window_hours: 48
  timezone: Asia/Shanghai
  api_timeout_seconds: 10
  bot_api_timeout_seconds: 10
  bot_proactive_message_limit: 2
  guardian_push_time_options: ["20:00", "21:00"]
  guardian_default_push_time: "20:30"
  growth_evidence_limit: 20
  growth_summary_max_tokens: 800
  daily_record_summary_max_tokens: 1200
chat_context:
  max_chars: 24000
  recent_turns: 8
  summary_max_chars: 3500
  message_max_chars: 4000
  tool_max_chars: 2000
question_bank:
  bili_search_page_size: 10
  bili_search_top_n: 3
  bili_search_timeout_seconds: 15
  search_timeout_seconds: 12
  review_timeout_seconds: 15
  official_source_site_seeds: {}
"""


def _write_config(tmp_path: Path, content: str = VALID_CONFIG) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_settings_accepts_valid_yaml(tmp_path: Path):
    config = load_config_settings(_write_config(tmp_path))

    assert isinstance(config, ConfigSettings)
    assert config.brand.name == "知了"
    assert config.question_bank.bili_search_top_n == 3


def test_load_config_settings_rejects_unknown_fields(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG + "unexpected: true\n")

    with pytest.raises(ValueError, match="配置文件校验失败") as exc_info:
        load_config_settings(path)

    assert "unexpected" in str(exc_info.value)


def test_load_config_settings_rejects_wrong_types(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG.replace("timeout_seconds: 60", 'timeout_seconds: "60"'))

    with pytest.raises(ValueError, match="llm.timeout_seconds"):
        load_config_settings(path)


def test_load_config_settings_rejects_blank_brand(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG.replace("name: 知了", 'name: "   "'))

    with pytest.raises(ValueError, match="brand.name"):
        load_config_settings(path)


def test_load_config_settings_rejects_out_of_range_values(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG.replace("tool_timeout_seconds: 8", "tool_timeout_seconds: 0"))

    with pytest.raises(ValueError, match="agent.tool_timeout_seconds"):
        load_config_settings(path)


def test_load_config_settings_rejects_missing_file(tmp_path: Path):
    with pytest.raises(RuntimeError, match="配置文件不存在"):
        load_config_settings(tmp_path / "missing.yaml")


def _seed_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """补齐 SecretSettings 必填环境变量（DB + JWT + WECHAT_URL 系）。"""
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_USER", "studybuddy")
    monkeypatch.setenv("DB_PASSWORD", "db-secret")
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-value")
    monkeypatch.setenv("WECHAT_TOKEN", "wechat-token")
    monkeypatch.setenv("WECHAT_OFFICIAL_ACCOUNT_QR_URL", "https://example.com/qr")
    monkeypatch.setenv("WECHAT_ACCESS_TOKEN_URL", "https://example.com/token")
    monkeypatch.setenv("WECHAT_CUSTOMER_MESSAGE_URL", "https://example.com/msg")
    monkeypatch.setenv("WECHAT_BOT_SERVICE_URL", "https://example.com/bot")
    monkeypatch.setenv("WECHAT_BOT_INTERNAL_TOKEN", "bot-internal-token")
    monkeypatch.setenv("WECHAT_PARENT_INVITATION_URL", "https://example.com/invite")


def test_secret_settings_masks_secret_values(monkeypatch: pytest.MonkeyPatch):
    _seed_secret_env(monkeypatch)

    secrets = SecretSettings(_env_file=None)

    assert isinstance(secrets.DB_PASSWORD, SecretStr)
    assert secrets.DB_PASSWORD.get_secret_value() == "db-secret"
    assert "db-secret" not in repr(secrets)
    assert "jwt-secret-value" not in repr(secrets)


def test_secret_settings_rejects_short_jwt_secret(monkeypatch: pytest.MonkeyPatch):
    _seed_secret_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "short")

    with pytest.raises(ValidationError):
        SecretSettings(_env_file=None)


def test_load_secret_settings_does_not_expose_invalid_secret(monkeypatch: pytest.MonkeyPatch):
    _seed_secret_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "visible-short")

    with pytest.raises(RuntimeError, match="JWT_SECRET") as exc_info:
        load_secret_settings()

    assert "visible-short" not in str(exc_info.value)


def test_load_config_settings_rejects_invalid_timezone(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG.replace("timezone: Asia/Shanghai", "timezone: Not/AZone"))

    with pytest.raises(ValueError, match="wechat.timezone"):
        load_config_settings(path)


def test_load_config_settings_rejects_invalid_push_time(tmp_path: Path):
    path = _write_config(tmp_path, VALID_CONFIG.replace('guardian_default_push_time: "20:30"', 'guardian_default_push_time: "99:99"'))

    with pytest.raises(ValueError, match="wechat.guardian_default_push_time"):
        load_config_settings(path)


def test_config_models_are_frozen(tmp_path: Path):
    config = load_config_settings(_write_config(tmp_path))

    with pytest.raises(ValidationError):
        config.brand.name = "其他"  # type: ignore[misc]


def test_agent_config_rejects_unknown_fields(tmp_path: Path):
    """agent 段未知字段（extra=forbid）必须拒绝。"""
    path = _write_config(
        tmp_path, VALID_CONFIG.replace("  tool_timeout_seconds: 8\n", "  tool_timeout_seconds: 8\n  unknown_key: 1\n")
    )

    with pytest.raises(ValueError, match="agent.unknown_key"):
        load_config_settings(path)


def test_agent_config_rejects_wrong_type(tmp_path: Path):
    """词表类型错误（int 代替字符串列表）必须拒绝。"""
    path = _write_config(tmp_path, VALID_CONFIG.replace('route_keywords: ["卷子", "试卷"]', "route_keywords: 123"))

    with pytest.raises(ValueError, match="agent.practice_exam.route_keywords"):
        load_config_settings(path)


def test_agent_config_rejects_duplicate_keywords(tmp_path: Path):
    """词表重复元素必须拒绝。"""
    path = _write_config(tmp_path, VALID_CONFIG.replace('route_keywords: ["卷子", "试卷"]', 'route_keywords: ["卷子", "卷子"]'))

    with pytest.raises(ValueError, match="agent.practice_exam.route_keywords"):
        load_config_settings(path)


def test_agent_config_rejects_min_gt_max(tmp_path: Path):
    """min_questions > max_questions 必须拒绝。"""
    path = _write_config(tmp_path, VALID_CONFIG.replace("min_questions: 1\n    max_questions: 3", "min_questions: 5\n    max_questions: 3"))

    with pytest.raises(ValueError, match="agent.light_practice"):
        load_config_settings(path)


def test_agent_config_rejects_invalid_subject_code(tmp_path: Path):
    """科目代码非小写标识符必须拒绝。"""
    path = _write_config(tmp_path, VALID_CONFIG.replace('subject_codes: ["math", "english", "chinese"]', 'subject_codes: ["Math", "english"]'))

    with pytest.raises(ValueError, match="agent.practice_exam.subject_codes"):
        load_config_settings(path)


def test_tool_schema_subject_enum_matches_config():
    """工具 schema 科目枚举与 config.yaml subject_codes 保持一致（唯一来源）。"""
    from app.config import settings
    from app.features.agent import tools

    assert set(tools._SUBJECT_CODES) == set(settings.config.agent.practice_exam.subject_codes)
    for tool in (tools._TOOL_CREATE_EXAM, tools._TOOL_CREATE_PRACTICE_EXAM):
        enum = tool["input_schema"]["properties"]["subject"]["enum"]
        assert set(enum) == set(settings.config.agent.practice_exam.subject_codes)
