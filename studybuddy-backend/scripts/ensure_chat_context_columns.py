"""Ensure rolling chat context fields exist in production MySQL."""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


COLUMNS = {
    "context_summary": "TEXT NULL",
    "context_summary_message_id": "BIGINT NULL",
}


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM chat_sessions")).all()}
        added: list[str] = []
        for name, ddl in COLUMNS.items():
            if name in existing:
                continue
            db.execute(text(f"ALTER TABLE chat_sessions ADD COLUMN {name} {ddl}"))
            added.append(name)
        db.commit()

    if added:
        print("已补充 chat_sessions 上下文字段：" + "、".join(added))
    else:
        print("chat_sessions 上下文字段已存在，无需修改")


if __name__ == "__main__":
    main()
