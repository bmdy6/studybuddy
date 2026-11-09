"""幂等添加 exam_assignments.plan_item_id 列与索引（U-045 学生自练卷关联计划项）。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS 判断后 ALTER。
部署时 deploy_backend.sh 调用，可重复执行。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

COLUMN = "plan_item_id"
INDEX_NAME = "idx_exam_assignments_plan_item"


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM exam_assignments")).all()}
        added: list[str] = []
        if COLUMN not in existing:
            db.execute(
                text(
                    f"ALTER TABLE exam_assignments ADD COLUMN {COLUMN} "
                    "BIGINT NULL COMMENT '自练卷关联的学习计划项（纯自练为空）'"
                )
            )
            added.append(COLUMN)
        index_exists = (
            db.execute(
                text("SHOW INDEX FROM exam_assignments WHERE Key_name = :n"),
                {"n": INDEX_NAME},
            ).first()
            is not None
        )
        if not index_exists:
            db.execute(text(f"CREATE INDEX {INDEX_NAME} ON exam_assignments ({COLUMN})"))
            added.append(INDEX_NAME)
        db.commit()
        if added:
            print(f"ensure_practice_exam_assignment: added {added}")
        else:
            print("ensure_practice_exam_assignment: column and index exist, skip")


if __name__ == "__main__":
    main()
