"""幂等迁移：chat_sessions 按模式隔离主会话。

1. 加 mode 列（study=学习默认 / hobby=兴趣爱好）
2. 主会话唯一约束从 uk_chat_sessions_primary_student(primary_student_id)
   换成 uk_chat_sessions_primary_mode(primary_student_id, mode)——每个模式一个主会话。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS / SHOW INDEX 判断后执行。
可重复执行。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

OLD_INDEX = "uk_chat_sessions_primary_student"
NEW_INDEX = "uk_chat_sessions_primary_mode"


def main() -> None:
    with SessionLocal() as db:
        cols = {row[0] for row in db.execute(text("SHOW COLUMNS FROM chat_sessions")).all()}
        if "mode" not in cols:
            db.execute(
                text(
                    "ALTER TABLE chat_sessions ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'study' "
                    "COMMENT '模式：study=学习(默认) / hobby=兴趣爱好'"
                )
            )
            db.commit()
            print("ensure_chat_session_mode: added chat_sessions.mode (default study)")
        else:
            print("ensure_chat_session_mode: column exists, skip")

        # 唯一索引：删旧加新（复合 primary_student_id+mode）。SHOW INDEX 列序：Table,Non_unique,Key_name,...
        indexes = {row[2] for row in db.execute(text("SHOW INDEX FROM chat_sessions")).all()}
        if NEW_INDEX not in indexes:
            if OLD_INDEX in indexes:
                db.execute(text(f"ALTER TABLE chat_sessions DROP INDEX {OLD_INDEX}"))
                print(f"ensure_chat_session_mode: dropped legacy index {OLD_INDEX}")
            db.execute(
                text(
                    f"CREATE UNIQUE INDEX {NEW_INDEX} ON chat_sessions (primary_student_id, mode)"
                )
            )
            db.commit()
            print(f"ensure_chat_session_mode: index {OLD_INDEX} -> {NEW_INDEX}")
        else:
            print(f"ensure_chat_session_mode: index {NEW_INDEX} exists, skip")


if __name__ == "__main__":
    main()
