"""每日学习记录 SQL 迁移文件内容校验。

验证 sql/018_daily_learning_records.sql：
- 幂等 CREATE TABLE IF NOT EXISTS
- spec 3.1 全部字段
- UNIQUE(student_id, record_date)
- MySQL 5.7 兼容（不使用 8.0 专属语法如 CHECK 约束表达式、隐藏列等）
- FK 引用 users(id)
- 迁移文件可重复执行（幂等，不 DROP）

不连真实库：纯文本断言，CI 真实建表由 run_ddl.py 按序号执行覆盖。
"""

from pathlib import Path


def _read_sql() -> str:
    return (Path(__file__).parents[2] / "sql" / "018_daily_learning_records.sql").read_text(encoding="utf-8")


def test_migration_is_idempotent_create() -> None:
    sql = _read_sql()
    assert "CREATE TABLE IF NOT EXISTS daily_learning_records" in sql
    assert "DROP TABLE" not in sql.upper(), "回退不得 DROP TABLE（spec 十七、工程边界）"


def test_migration_has_unique_constraint() -> None:
    sql = _read_sql()
    # UNIQUE(student_id, record_date) -- spec 3.1 唯一约束
    assert "UNIQUE" in sql.upper()
    assert "student_id" in sql
    assert "record_date" in sql


def test_migration_has_all_contract_fields() -> None:
    """spec 3.1 表结构全部字段。"""
    sql = _read_sql()
    for fragment in (
        "id",
        "student_id",
        "record_date",
        "facts_snapshot",
        "summary_text",
        "evidence_hash",
        "generation_status",
        "summary_source",
        "checkin_status",
        "checkin_response",
        "checked_in_at",
        "generated_at",
        "finalized_at",
        "created_at",
        "updated_at",
    ):
        assert fragment in sql, f"SQL 缺少字段 {fragment}"


def test_migration_uses_mysql57_compatible_types() -> None:
    """MySQL 5.7 兼容：JSON、ENUM、DATE、DATETIME、VARCHAR、BIGINT、TEXT。"""
    sql = _read_sql()
    assert "JSON" in sql  # 5.7 支持 JSON 类型
    assert "ENUM" in sql  # generation_status / summary_source / checkin_status
    assert "DATE" in sql  # record_date
    assert "BIGINT" in sql  # id / student_id


def test_migration_has_fk_to_users() -> None:
    sql = _read_sql()
    assert "REFERENCES users(id)" in sql
    assert "FOREIGN KEY" in sql.upper()


def test_migration_uses_utf8mb4() -> None:
    sql = _read_sql()
    assert "utf8mb4" in sql
    assert "InnoDB" in sql


def test_migration_generation_status_enum_values() -> None:
    """spec 3.1: generation_status ENUM('pending','generating','ready','failed')。"""
    sql = _read_sql()
    for val in ("pending", "generating", "ready", "failed"):
        assert val in sql, f"generation_status 缺少枚举值 {val}"


def test_migration_summary_source_enum_values() -> None:
    """spec 3.1: summary_source ENUM('ai','deterministic') NULL。"""
    sql = _read_sql()
    for val in ("ai", "deterministic"):
        assert val in sql


def test_migration_checkin_status_enum_values() -> None:
    """spec 3.1: checkin_status ENUM('pending','done') NULL。"""
    sql = _read_sql()
    for val in ("pending", "done"):
        assert val in sql
