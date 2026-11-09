"""Ensure exam_batches answer review fields exist in production MySQL."""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


COLUMNS = {
    "recognized_markdown": "TEXT NULL",
    "answer_review_state": "JSON NULL",
    "answer_review_confirmed_at": "DATETIME NULL",
}


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM exam_batches")).all()}
        added: list[str] = []
        for name, ddl in COLUMNS.items():
            if name in existing:
                continue
            db.execute(text(f"ALTER TABLE exam_batches ADD COLUMN {name} {ddl}"))
            added.append(name)
        db.commit()

    if added:
        print("已补充 exam_batches 作答核对字段：" + "、".join(added))
    else:
        print("exam_batches 作答核对字段已存在，无需修改")


if __name__ == "__main__":
    main()
