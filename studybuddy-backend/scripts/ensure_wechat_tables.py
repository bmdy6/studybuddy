import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.config import settings


TABLES = [
    """
    CREATE TABLE IF NOT EXISTS wechat_bind_sessions (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      user_id BIGINT NULL,
      purpose ENUM('account_bind', 'guardian_invite') NOT NULL DEFAULT 'account_bind',
      channel VARCHAR(32) NOT NULL,
      provider_session_id VARCHAR(128) NULL,
      provider_account_id VARCHAR(128) NULL,
      invited_by_user_id BIGINT NULL,
      scene VARCHAR(64) NOT NULL UNIQUE,
      bind_code VARCHAR(16) NOT NULL UNIQUE,
      qr_value VARCHAR(512) NOT NULL,
      status ENUM('pending', 'bound', 'expired', 'cancelled') NOT NULL DEFAULT 'pending',
      wechat_openid VARCHAR(128) NULL,
      expires_at DATETIME NOT NULL,
      bound_at DATETIME NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_wechat_bind_sessions_user_id (user_id),
      INDEX idx_wechat_bind_sessions_channel (channel),
      INDEX idx_wechat_bind_sessions_provider_session (provider_session_id),
      INDEX idx_wechat_bind_sessions_provider_account (provider_account_id),
      INDEX idx_wechat_bind_sessions_invited_by_user (invited_by_user_id),
      INDEX idx_wechat_bind_sessions_scene (scene),
      INDEX idx_wechat_bind_sessions_bind_code (bind_code),
      INDEX idx_wechat_bind_sessions_openid (wechat_openid),
      CONSTRAINT fk_wechat_bind_sessions_user FOREIGN KEY (user_id) REFERENCES users(id),
      CONSTRAINT fk_wechat_bind_sessions_invited_by_user
        FOREIGN KEY (invited_by_user_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS wechat_accounts (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      user_id BIGINT NOT NULL,
      chat_session_id BIGINT NULL,
      channel VARCHAR(32) NOT NULL,
      provider_account_id VARCHAR(128) NULL,
      openid VARCHAR(128) NOT NULL,
      guardian_onboarding_status ENUM('awaiting_push_time', 'completed') NOT NULL DEFAULT 'completed',
      guardian_default_push_time VARCHAR(5) NULL,
      selected_student_id BIGINT NULL,
      active_identity_key VARCHAR(64) NULL,
      nickname VARCHAR(128) NULL,
      status ENUM('active', 'unbound') NOT NULL DEFAULT 'active',
      bound_at DATETIME NOT NULL,
      unbound_at DATETIME NULL,
      login_token_hash VARCHAR(64) NULL UNIQUE,
      login_token_expires_at DATETIME NULL,
      login_token_used_at DATETIME NULL,
      last_interacted_at DATETIME NULL,
      reminder_times JSON NULL,
      last_reminder_sent_at DATETIME NULL,
      last_reminder_claimed_minute VARCHAR(16) NULL,
      proactive_message_count INT NOT NULL DEFAULT 0,
      proactive_message_window_started_at DATETIME NULL,
      revocation_pending TINYINT(1) NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_wechat_accounts_user_id (user_id),
      INDEX idx_wechat_accounts_chat_session (chat_session_id),
      INDEX idx_wechat_accounts_channel (channel),
      INDEX idx_wechat_accounts_provider_account (provider_account_id),
      INDEX idx_wechat_accounts_openid (openid),
      INDEX idx_wechat_accounts_selected_student (selected_student_id),
      UNIQUE KEY uq_wechat_accounts_active_identity (active_identity_key),
      CONSTRAINT fk_wechat_accounts_user FOREIGN KEY (user_id) REFERENCES users(id),
      CONSTRAINT fk_wechat_accounts_selected_student
        FOREIGN KEY (selected_student_id) REFERENCES users(id) ON DELETE SET NULL,
      CONSTRAINT fk_wechat_accounts_chat_session
        FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS wechat_guardian_student_contexts (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      account_id BIGINT NOT NULL,
      student_id BIGINT NOT NULL,
      chat_session_id BIGINT NULL,
      push_time VARCHAR(5) NOT NULL,
      paused TINYINT(1) NOT NULL DEFAULT 0,
      status ENUM('active', 'unbound') NOT NULL DEFAULT 'active',
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uq_wechat_guardian_student (account_id, student_id),
      INDEX idx_wechat_guardian_context_account (account_id),
      INDEX idx_wechat_guardian_context_student (student_id),
      CONSTRAINT fk_wechat_guardian_context_account FOREIGN KEY (account_id) REFERENCES wechat_accounts(id) ON DELETE CASCADE,
      CONSTRAINT fk_wechat_guardian_context_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
      CONSTRAINT fk_wechat_guardian_context_chat FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def main() -> None:
    with SessionLocal() as db:
        for ddl in TABLES:
            db.execute(text(ddl))
        user_columns = {row[0] for row in db.execute(text("SHOW COLUMNS FROM users")).all()}
        if "web_login_enabled" not in user_columns:
            db.execute(
                text(
                    "ALTER TABLE users ADD COLUMN "
                    "web_login_enabled TINYINT(1) NOT NULL DEFAULT 1"
                )
            )
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM wechat_accounts")).all()}
        columns = {
            "channel": "VARCHAR(32) NULL",
            "chat_session_id": "BIGINT NULL",
            "provider_account_id": "VARCHAR(128) NULL",
            "guardian_onboarding_status": "ENUM('awaiting_push_time', 'completed') NOT NULL DEFAULT 'completed'",
            "guardian_default_push_time": "VARCHAR(5) NULL",
            "selected_student_id": "BIGINT NULL",
            "login_token_hash": "VARCHAR(64) NULL UNIQUE",
            "login_token_expires_at": "DATETIME NULL",
            "login_token_used_at": "DATETIME NULL",
            "last_interacted_at": "DATETIME NULL",
            "reminder_times": "JSON NULL",
            "last_reminder_sent_at": "DATETIME NULL",
            "last_reminder_claimed_minute": "VARCHAR(16) NULL",
            "proactive_message_window_started_at": "DATETIME NULL",
            "revocation_pending": "TINYINT(1) NOT NULL DEFAULT 0",
        }
        for name, ddl in columns.items():
            if name not in existing:
                db.execute(text(f"ALTER TABLE wechat_accounts ADD COLUMN {name} {ddl}"))
        if "channel" not in existing:
            db.execute(text("UPDATE wechat_accounts SET channel = 'official_account' WHERE channel IS NULL"))
            db.execute(text("ALTER TABLE wechat_accounts MODIFY COLUMN channel VARCHAR(32) NOT NULL"))
        if "proactive_message_count" not in existing:
            db.execute(
                text("ALTER TABLE wechat_accounts ADD COLUMN proactive_message_count INT NULL")
            )
            db.execute(text("UPDATE wechat_accounts SET proactive_message_count = 0"))
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts MODIFY COLUMN "
                    "proactive_message_count INT NOT NULL DEFAULT 0"
                )
            )
        if "active_identity_key" not in existing:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD COLUMN "
                    "active_identity_key VARCHAR(64) NULL"
                )
            )
        db.execute(
            text(
                "UPDATE wechat_accounts SET active_identity_key = "
                "SHA2(CONCAT(channel, CHAR(0), COALESCE(provider_account_id, ''), "
                "CHAR(0), openid), 256) WHERE status = 'active' "
                "AND active_identity_key IS NULL"
            )
        )
        duplicate_identities = db.execute(
            text(
                "SELECT active_identity_key FROM wechat_accounts "
                "WHERE active_identity_key IS NOT NULL GROUP BY active_identity_key "
                "HAVING COUNT(*) > 1"
            )
        ).all()
        if duplicate_identities:
            raise RuntimeError("存在重复的有效微信渠道身份，请先人工核对")
        identity_indexes = db.execute(
            text(
                "SHOW INDEX FROM wechat_accounts "
                "WHERE Key_name = 'uq_wechat_accounts_active_identity'"
            )
        ).all()
        if not identity_indexes:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD UNIQUE KEY "
                    "uq_wechat_accounts_active_identity (active_identity_key)"
                )
            )
        chat_session_indexes = db.execute(
            text(
                "SHOW INDEX FROM wechat_accounts "
                "WHERE Key_name = 'idx_wechat_accounts_chat_session'"
            )
        ).all()
        if not chat_session_indexes:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD INDEX "
                    "idx_wechat_accounts_chat_session (chat_session_id)"
                )
            )
        selected_student_indexes = db.execute(
            text(
                "SHOW INDEX FROM wechat_accounts "
                "WHERE Key_name = 'idx_wechat_accounts_selected_student'"
            )
        ).all()
        if not selected_student_indexes:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD INDEX "
                    "idx_wechat_accounts_selected_student (selected_student_id)"
                )
            )
        chat_session_foreign_keys = db.execute(
            text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'wechat_accounts' "
                "AND COLUMN_NAME = 'chat_session_id' "
                "AND REFERENCED_TABLE_NAME = 'chat_sessions'"
            )
        ).all()
        if not chat_session_foreign_keys:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD CONSTRAINT "
                    "fk_wechat_accounts_chat_session FOREIGN KEY (chat_session_id) "
                    "REFERENCES chat_sessions(id) ON DELETE SET NULL"
                )
            )
        selected_student_foreign_keys = db.execute(
            text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'wechat_accounts' "
                "AND COLUMN_NAME = 'selected_student_id' "
                "AND REFERENCED_TABLE_NAME = 'users'"
            )
        ).all()
        if not selected_student_foreign_keys:
            db.execute(
                text(
                    "ALTER TABLE wechat_accounts ADD CONSTRAINT "
                    "fk_wechat_accounts_selected_student FOREIGN KEY (selected_student_id) "
                    "REFERENCES users(id) ON DELETE SET NULL"
                )
            )
        bind_existing = {
            row[0] for row in db.execute(text("SHOW COLUMNS FROM wechat_bind_sessions")).all()
        }
        bind_columns = {
            "channel": "VARCHAR(32) NULL",
            "provider_session_id": "VARCHAR(128) NULL",
            "provider_account_id": "VARCHAR(128) NULL",
            "invited_by_user_id": "BIGINT NULL",
            "purpose": "ENUM('account_bind', 'guardian_invite') NOT NULL DEFAULT 'account_bind'",
        }
        for name, ddl in bind_columns.items():
            if name not in bind_existing:
                db.execute(text(f"ALTER TABLE wechat_bind_sessions ADD COLUMN {name} {ddl}"))
        if "channel" not in bind_existing:
            db.execute(text("UPDATE wechat_bind_sessions SET channel = 'official_account' WHERE channel IS NULL"))
            db.execute(text("ALTER TABLE wechat_bind_sessions MODIFY COLUMN channel VARCHAR(32) NOT NULL"))
        bind_user_id = next(
            (row for row in db.execute(text("SHOW COLUMNS FROM wechat_bind_sessions")).all() if row[0] == "user_id"),
            None,
        )
        if not bind_user_id or len(bind_user_id) < 3 or bind_user_id[2] != "YES":
            db.execute(
                text("ALTER TABLE wechat_bind_sessions MODIFY COLUMN user_id BIGINT NULL")
            )
        invitation_foreign_keys = db.execute(
            text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'wechat_bind_sessions' "
                "AND COLUMN_NAME = 'invited_by_user_id' "
                "AND REFERENCED_TABLE_NAME = 'users'"
            )
        ).all()
        if not invitation_foreign_keys:
            db.execute(
                text(
                    "ALTER TABLE wechat_bind_sessions ADD CONSTRAINT "
                    "fk_wechat_bind_sessions_invited_by_user "
                    "FOREIGN KEY (invited_by_user_id) REFERENCES users(id)"
                )
            )
        default_push_time = settings.WECHAT_GUARDIAN_DEFAULT_PUSH_TIME.strip()
        db.execute(
            text(
                "UPDATE wechat_accounts a JOIN users u ON u.id = a.user_id "
                "SET a.guardian_default_push_time = :default_push_time "
                "WHERE a.channel = 'ilink_bot' AND a.status = 'active' "
                "AND u.role = 'teacher' AND a.guardian_default_push_time IS NULL"
            ),
            {"default_push_time": default_push_time},
        )
        db.execute(
            text(
                "INSERT INTO wechat_guardian_student_contexts "
                "(account_id, student_id, push_time, paused, status) "
                "SELECT a.id, ts.student_id, a.guardian_default_push_time, 0, 'active' "
                "FROM wechat_accounts a "
                "JOIN users u ON u.id = a.user_id "
                "JOIN teacher_students ts ON ts.teacher_id = a.user_id "
                "LEFT JOIN wechat_guardian_student_contexts c "
                "ON c.account_id = a.id AND c.student_id = ts.student_id "
                "WHERE a.channel = 'ilink_bot' AND a.status = 'active' "
                "AND u.role = 'teacher' AND c.id IS NULL"
            )
        )
        db.execute(
            text(
                "UPDATE wechat_accounts a JOIN ("
                "SELECT c.account_id, MIN(c.student_id) AS student_id "
                "FROM wechat_guardian_student_contexts c "
                "WHERE c.status = 'active' GROUP BY c.account_id"
                ") selected ON selected.account_id = a.id "
                "SET a.selected_student_id = selected.student_id "
                "WHERE a.selected_student_id IS NULL"
            )
        )
        db.commit()
    print("微信绑定与登录字段已存在或已创建")


if __name__ == "__main__":
    main()
