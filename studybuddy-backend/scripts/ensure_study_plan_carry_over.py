"""幂等添加 study_plans.source_plan_id，支持旧计划沿用到今天。"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

COLUMN = "source_plan_id"
COLUMN_DDL = "BIGINT NULL COMMENT '沿用旧计划时的来源计划 id'"
UNIQUE_INDEX = "uk_study_plans_source_plan"
FOREIGN_KEY = "fk_study_plans_source_plan"


def main() -> None:
    with SessionLocal() as db:
        existing_columns = {row[0] for row in db.execute(text("SHOW COLUMNS FROM study_plans")).all()}
        if COLUMN not in existing_columns:
            db.execute(text(f"ALTER TABLE study_plans ADD COLUMN {COLUMN} {COLUMN_DDL}"))

        existing_indexes = {row[2] for row in db.execute(text("SHOW INDEX FROM study_plans")).all()}
        if UNIQUE_INDEX not in existing_indexes:
            db.execute(text(f"ALTER TABLE study_plans ADD UNIQUE KEY {UNIQUE_INDEX} ({COLUMN})"))

        database = db.execute(text("SELECT DATABASE()")).scalar_one()
        existing_foreign_keys = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT CONSTRAINT_NAME "
                    "FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = :database "
                    "AND TABLE_NAME = 'study_plans' "
                    "AND CONSTRAINT_NAME = :constraint"
                ),
                {"database": database, "constraint": FOREIGN_KEY},
            ).all()
        }
        if FOREIGN_KEY not in existing_foreign_keys:
            db.execute(
                text(
                    f"ALTER TABLE study_plans ADD CONSTRAINT {FOREIGN_KEY} "
                    "FOREIGN KEY (source_plan_id) REFERENCES study_plans(id) ON DELETE SET NULL"
                )
            )
        db.commit()
        print("ensure_study_plan_carry_over: ready")


if __name__ == "__main__":
    main()
