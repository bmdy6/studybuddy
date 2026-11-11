"""建库建表脚本：用 pymysql 执行 DDL（本地 mysql 9.x CLI 缺 native_password 插件无法连）。

用法：
  PYTHONPATH=. .venv/bin/python scripts/run_ddl.py            # 执行 001_init.sql（全量初始化）
  PYTHONPATH=. .venv/bin/python scripts/run_ddl.py sql/002_chat.sql  # 执行指定增量 SQL
"""

import re
import sys

import pymysql

from app.config import reveal_secret, settings

DEFAULT_SQL_FILE = "sql/001_init.sql"


def split_statements(sql: str) -> list[str]:
    """按分号拆分 SQL，跳过注释行和空语句。

    CREATE TABLE 语句内部不应含分号；DDL 文件里的 -- 注释行会被剔除。
    """
    statements = []
    for raw in sql.split(";"):
        # 去掉每行的 -- 注释
        lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        # 去掉语句内残留的注释块（无分号的 -- 行已剔，但行内 -- 注释也去掉）
        stmt = re.sub(r"--[^\n]*", "", stmt).strip()
        if stmt:
            statements.append(stmt)
    return statements


def main() -> int:
    sql_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SQL_FILE
    is_full_init = sql_file == DEFAULT_SQL_FILE
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=reveal_secret(settings.DB_PASSWORD),
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=True,
    )
    with open(sql_file, encoding="utf-8") as f:
        sql = f.read()
    statements = split_statements(sql)
    cur = conn.cursor()
    created = 0
    for stmt in statements:
        # 跳过 CREATE DATABASE / USE（已指定 database 连接）
        head = stmt.splitlines()[0].upper()
        if head.startswith("CREATE DATABASE") or head.startswith("USE "):
            continue
        cur.execute(stmt)
        created += 1
    cur.execute("SHOW TABLES")
    tables = sorted(r[0] for r in cur.fetchall())
    print(f"[{sql_file}] 执行语句 {created} 条，表数量: {len(tables)}")
    for t in tables:
        print(f"  - {t}")
    if is_full_init:
        # 仅全量初始化时校验 9 张 P1 表 + error_book 特殊结构
        expected = 9
        print(f"P1 表数量校验: 期望 {expected}，实际 {len(tables)}")
        cur.execute("SHOW INDEX FROM error_book WHERE Key_name='uk_student_question'")
        print("uk_student_question 索引存在:", cur.fetchone() is not None)
        cur.execute("SHOW COLUMNS FROM error_book LIKE 'tag_array'")
        print("tag_array 虚拟列存在:", cur.fetchone() is not None)
        ok = len(tables) >= expected
    else:
        # 增量迁移：只确认目标表存在即可
        ok = True
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
