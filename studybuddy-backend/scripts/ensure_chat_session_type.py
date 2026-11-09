"""幂等添加 chat_sessions 的 session_type/plan_id/plan_item_id/status/context_version（U-042 任务会话）。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS 判断后 ALTER。
部署时 deploy_backend.sh 调用，可重复执行。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

COLUMNS = {
    "session_type": "VARCHAR(16) NOT NULL DEFAULT 'main' COMMENT 'main|task'",
    "plan_id": "BIGINT NULL COMMENT 'task 关联的学习计划'",
    "plan_item_id": "BIGINT NULL COMMENT 'task 关联的计划项'",
    "status": "VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active|archived'",
    "context_version": "INT NOT NULL DEFAULT 0 COMMENT 'task 上下文版本'",
}

INDEX_NAME = "uq_chat_sessions_plan_item_id"


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM chat_sessions")).all()}
        added: list[str] = []
        for name, ddl in COLUMNS.items():
            if name in existing:
                continue
            db.execute(text(f"ALTER TABLE chat_sessions ADD COLUMN {name} {ddl}"))
            added.append(name)
        # plan_item_id 唯一索引（MySQL 5.7 UNIQUE 允许多 NULL，main session 不冲突）
        index_exists = (
            db.execute(
                text("SHOW INDEX FROM chat_sessions WHERE Key_name = :n"),
                {"n": INDEX_NAME},
            ).first()
            is not None
        )
        if not index_exists:
            db.execute(text(f"CREATE UNIQUE INDEX {INDEX_NAME} ON chat_sessions (plan_item_id)"))
            added.append(INDEX_NAME)
        db.commit()
        if added:
            print(f"ensure_chat_session_type: added {added}")
        else:
            print("ensure_chat_session_type: all columns and index exist, skip")


if __name__ == "__main__":
    main()
