from __future__ import annotations

import runpy
from pathlib import Path


class _Result:
    def __init__(self, rows=()):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        self.statements.append(sql)
        if "SHOW COLUMNS FROM wechat_accounts" in sql:
            return _Result((("id",),))
        if "SHOW COLUMNS FROM wechat_bind_sessions" in sql:
            return _Result((("id",),))
        return _Result()

    def commit(self):
        return None


def test_ensure_wechat_tables_backfills_existing_rows_by_channel(monkeypatch) -> None:
    session = _Session()
    monkeypatch.setattr("app.database.SessionLocal", lambda: session)
    script = Path(__file__).parents[2] / "scripts" / "ensure_wechat_tables.py"

    runpy.run_path(str(script), run_name="__main__")

    sql = "\n".join(session.statements)
    assert "ADD COLUMN channel VARCHAR(32) NULL" in sql
    assert "UPDATE wechat_accounts SET channel = 'official_account'" in sql
    assert "UPDATE wechat_bind_sessions SET channel = 'official_account'" in sql
    assert "MODIFY COLUMN channel VARCHAR(32) NOT NULL" in sql
    assert "ADD COLUMN provider_account_id VARCHAR(128) NULL" in sql
    assert "ADD COLUMN provider_session_id VARCHAR(128) NULL" in sql
    assert "ADD COLUMN invited_by_user_id BIGINT NULL" in sql
    assert "ADD COLUMN purpose ENUM('account_bind', 'guardian_invite')" in sql
    assert "MODIFY COLUMN user_id BIGINT NULL" in sql
    assert "information_schema.KEY_COLUMN_USAGE" in sql
    assert "ADD CONSTRAINT fk_wechat_bind_sessions_invited_by_user" in sql
    assert "ADD COLUMN proactive_message_count INT NULL" in sql
    assert "UPDATE wechat_accounts SET proactive_message_count = 0" in sql
    assert "MODIFY COLUMN proactive_message_count INT NOT NULL DEFAULT 0" in sql
    assert "ADD COLUMN proactive_message_window_started_at DATETIME NULL" in sql
    assert "ADD COLUMN last_reminder_claimed_minute VARCHAR(16) NULL" in sql
    assert "ADD COLUMN revocation_pending TINYINT(1) NOT NULL DEFAULT 0" in sql
    assert "ADD COLUMN active_identity_key VARCHAR(64) NULL" in sql
    assert "ADD COLUMN guardian_onboarding_status" in sql
    assert "DEFAULT 'completed'" in sql
    assert "ADD COLUMN guardian_default_push_time VARCHAR(5) NULL" in sql
    assert "ADD COLUMN selected_student_id BIGINT NULL" in sql
    assert "ADD INDEX idx_wechat_accounts_selected_student" in sql
    assert "ADD CONSTRAINT fk_wechat_accounts_selected_student" in sql
    assert "INSERT INTO wechat_guardian_student_contexts" in sql
    assert "JOIN teacher_students" in sql
    assert "guardian_default_push_time" in sql
    assert "selected_student_id" in sql and "MIN(c.student_id)" in sql
    assert "UPDATE wechat_accounts" in sql and "SHA2" in sql
    assert "ADD UNIQUE KEY uq_wechat_accounts_active_identity" in sql
    assert "ADD COLUMN chat_session_id BIGINT NULL" in sql
    assert "ADD INDEX idx_wechat_accounts_chat_session" in sql
    assert "ADD CONSTRAINT fk_wechat_accounts_chat_session" in sql
    assert "REFERENCES chat_sessions(id) ON DELETE SET NULL" in sql


def test_wechat_schema_sql_contains_current_shared_bot_fields() -> None:
    schema = (Path(__file__).parents[2] / "sql" / "017_wechat_bindings.sql").read_text()

    for fragment in (
        "invited_by_user_id BIGINT NULL",
        "user_id BIGINT NULL",
        "purpose ENUM('account_bind', 'guardian_invite')",
        "active_identity_key VARCHAR(64) NULL",
        "guardian_onboarding_status ENUM('awaiting_push_time', 'completed')",
        "guardian_default_push_time VARCHAR(5) NULL",
        "selected_student_id BIGINT NULL",
        "last_reminder_claimed_minute VARCHAR(16) NULL",
        "proactive_message_count INT NOT NULL DEFAULT 0",
        "proactive_message_window_started_at DATETIME NULL",
        "revocation_pending TINYINT(1) NOT NULL DEFAULT 0",
        "chat_session_id BIGINT NULL",
        "INDEX idx_wechat_accounts_chat_session",
        "UNIQUE KEY uq_wechat_accounts_active_identity",
        "CONSTRAINT fk_wechat_accounts_chat_session",
        "CONSTRAINT fk_wechat_accounts_selected_student",
        "REFERENCES chat_sessions(id) ON DELETE SET NULL",
        "CONSTRAINT fk_wechat_bind_sessions_invited_by_user",
    ):
        assert fragment in schema


def test_chat_session_id_only_belongs_to_wechat_accounts() -> None:
    script = Path(__file__).parents[2] / "scripts" / "ensure_wechat_tables.py"
    namespace = runpy.run_path(str(script))
    bind_sessions_ddl = next(
        ddl for ddl in namespace["TABLES"] if "CREATE TABLE IF NOT EXISTS wechat_bind_sessions" in ddl
    )
    accounts_ddl = next(
        ddl for ddl in namespace["TABLES"] if "CREATE TABLE IF NOT EXISTS wechat_accounts" in ddl
    )

    assert "chat_session_id BIGINT NULL" not in bind_sessions_ddl
    assert "chat_session_id BIGINT NULL" in accounts_ddl

    schema = (Path(__file__).parents[2] / "sql" / "017_wechat_bindings.sql").read_text()
    bind_sessions_sql, accounts_sql = schema.split(
        "CREATE TABLE IF NOT EXISTS wechat_accounts", maxsplit=1
    )
    assert "chat_session_id BIGINT NULL" not in bind_sessions_sql
    assert "chat_session_id BIGINT NULL" in accounts_sql
