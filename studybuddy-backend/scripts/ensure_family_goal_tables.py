"""幂等建家庭目标与任务激励五张表（部署时 deploy_backend.sh 调用，可重复执行）。

建表语句与 sql/030_family_goals.sql 保持一致（CREATE TABLE IF NOT EXISTS，天然幂等）。
"""
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

DDL_PATH = Path(__file__).resolve().parent.parent / "sql" / "030_family_goals.sql"
TABLES = (
    "family_goals",
    "family_goal_tasks",
    "family_task_occurrences",
    "family_task_evidence",
    "family_reward_records",
)


def _split_statements(sql: str) -> list[str]:
    """按分号切 DDL，去掉注释行与空语句。"""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [stmt.strip() for stmt in "\n".join(lines).split(";")]
    return [stmt for stmt in statements if stmt]


def main() -> None:
    statements = _split_statements(DDL_PATH.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        for statement in statements:
            db.execute(text(statement))
        db.commit()
        missing = [
            table
            for table in TABLES
            if not db.execute(text("SHOW TABLES LIKE :table"), {"table": table}).first()
        ]
        if missing:
            raise SystemExit(f"ensure_family_goal_tables: 建表失败，缺失 {missing}")
        print(f"ensure_family_goal_tables: {len(TABLES)} 张表就绪")


if __name__ == "__main__":
    main()
