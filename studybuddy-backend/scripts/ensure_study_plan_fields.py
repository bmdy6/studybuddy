"""幂等添加 study_plans 的 description/context_refs/revision 字段（U-041 计划数据底座）。

MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，用 SHOW COLUMNS 判断后 ALTER。
部署时 deploy_backend.sh 调用，可重复执行。
"""
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

COLUMNS = {
    "description": "TEXT NULL COMMENT '计划完整说明'",
    "context_refs": "JSON NULL COMMENT '来源上下文引用'",
    "revision": "INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本号'",
}


def main() -> None:
    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(text("SHOW COLUMNS FROM study_plans")).all()}
        added: list[str] = []
        for name, ddl in COLUMNS.items():
            if name in existing:
                continue
            db.execute(text(f"ALTER TABLE study_plans ADD COLUMN {name} {ddl}"))
            added.append(name)
        db.commit()
        if added:
            print(f"ensure_study_plan_fields: added {added}")
        else:
            print("ensure_study_plan_fields: all columns exist, skip")


if __name__ == "__main__":
    main()
