"""Ensure chat_sessions.primary_student_id column exists in MySQL（幂等）。

注意：单列唯一索引 uk_chat_sessions_primary_student 已废弃——
模式隔离（PR #138）改用 uk_chat_sessions_primary_mode (primary_student_id, mode) 复合唯一，
由 ensure_chat_session_mode.py 负责创建。本脚本只保证列存在，不再创建/恢复旧索引，
避免部署时把废弃索引重建回来破坏复合唯一。

用法：
  PYTHONPATH=. .venv/bin/python scripts/ensure_chat_sessions_primary_student_id.py
"""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


COLUMN_NAME = "primary_student_id"
INDEX_NAME = "uk_chat_sessions_primary_student"


def _column_exists(db, column: str) -> bool:
    return column in {row[0] for row in db.execute(text("SHOW COLUMNS FROM chat_sessions")).all()}


def _index_exists(db, index: str) -> bool:
    rows = db.execute(text("SHOW INDEX FROM chat_sessions WHERE Key_name = :name"), {"name": index}).all()
    return len(rows) > 0


def main() -> None:
    with SessionLocal() as db:
        if not _column_exists(db, COLUMN_NAME):
            db.execute(
                text(
                    "ALTER TABLE chat_sessions "
                    f"ADD COLUMN {COLUMN_NAME} BIGINT NULL "
                    "COMMENT '学生主会话标识：仅学生自己的主会话写入学生 id，其余为 NULL'"
                )
            )
            db.commit()
            print(f"已补充 chat_sessions.{COLUMN_NAME} 列")
        else:
            print(f"chat_sessions.{COLUMN_NAME} 列已存在，无需修改")

        # 单列唯一索引已废弃（由 uk_chat_sessions_primary_mode 复合唯一取代，见 ensure_chat_session_mode.py）。
        # 不再创建，避免部署顺序导致旧索引重建、破坏模式隔离。


if __name__ == "__main__":
    main()
