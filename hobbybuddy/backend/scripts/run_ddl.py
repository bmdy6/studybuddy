"""建库建表脚本（复用底座 run_ddl 的思路）：执行 sql/001_hobby_init.sql。

用法：
  PYTHONPATH=. .venv/bin/python scripts/run_ddl.py
"""

import re
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hobby.config import settings  # noqa: E402

DEFAULT_SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "001_hobby_init.sql"


def split_statements(sql: str) -> list[str]:
    statements = []
    for raw in sql.split(";"):
        lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
        stmt = re.sub(r"--[^\n]*", "", "\n".join(lines)).strip()
        if stmt:
            statements.append(stmt)
    return statements


def main() -> None:
    secrets = settings.secrets
    conn = pymysql.connect(
        host=secrets.DB_HOST,
        port=secrets.DB_PORT,
        user=secrets.DB_USER,
        password=secrets.DB_PASSWORD,
        charset="utf8mb4",
    )
    try:
        sql = DEFAULT_SQL_FILE.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            for stmt in split_statements(sql):
                cur.execute(stmt)
        conn.commit()
        print(f"建库建表完成：{DEFAULT_SQL_FILE.name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
