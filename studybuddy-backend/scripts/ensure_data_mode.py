"""幂等迁移：业务数据表加 mode 列（study=学习默认 / hobby=兴趣爱好，逻辑隔离）。

涉及表：daily_learning_records / study_plans / study_plan_items / study_plan_draft / notes / materials。
daily_learning_records 唯一索引同步改复合 (student_id, mode, record_date)——
同学生同日期 study/hobby 各有记录，防跨模式覆盖。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS / SHOW INDEX 判断后执行。
可重复执行（部署脚本调用，存量数据默认 study 无损）。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

TABLES = [
    "daily_learning_records",
    "study_plans",
    "study_plan_items",
    "study_plan_draft",
    "notes",
    "materials",
]

DLR_OLD_INDEX = "uk_daily_learning_records_student_date"
DLR_NEW_INDEX = "uk_daily_learning_records_student_mode_date"


def main() -> None:
    with SessionLocal() as db:
        for table in TABLES:
            cols = {row[0] for row in db.execute(text(f"SHOW COLUMNS FROM {table}")).all()}
            if "mode" not in cols:
                db.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'study' "
                        "COMMENT '模式：study=学习(默认) / hobby=兴趣爱好'"
                    )
                )
                print(f"ensure_data_mode: added {table}.mode")
            else:
                print(f"ensure_data_mode: {table}.mode exists, skip")

        # daily_learning_records 唯一索引：单列日期 → 复合 (student_id, mode, record_date)
        indexes = {
            row[2] for row in db.execute(text("SHOW INDEX FROM daily_learning_records")).all()
        }
        if DLR_NEW_INDEX not in indexes:
            if DLR_OLD_INDEX in indexes:
                db.execute(text(f"ALTER TABLE daily_learning_records DROP INDEX {DLR_OLD_INDEX}"))
            db.execute(
                text(
                    f"ALTER TABLE daily_learning_records ADD UNIQUE INDEX {DLR_NEW_INDEX} "
                    "(student_id, mode, record_date)"
                )
            )
            print(f"ensure_data_mode: daily index {DLR_OLD_INDEX} -> {DLR_NEW_INDEX}")
        else:
            print(f"ensure_data_mode: {DLR_NEW_INDEX} exists, skip")
        db.commit()


if __name__ == "__main__":
    main()
