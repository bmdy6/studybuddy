"""memory_relations 表结构：必须同时有 created_at 与 updated_at（仓库数据库规范）。"""

from pathlib import Path


def test_model_declares_created_and_updated_at():
    from app.models.memory_relation import MemoryRelation

    table = MemoryRelation.__table__
    assert {"created_at", "updated_at"} <= {c.name for c in table.columns}
    updated = table.c.updated_at
    assert updated.server_default is not None, "updated_at 需要 server_default=func.now()"
    assert updated.onupdate is not None, "updated_at 需要 onupdate=func.now()"


def test_sql_ddl_declares_updated_at():
    sql = (Path(__file__).resolve().parents[3] / "sql" / "029_memory_relations.sql").read_text(encoding="utf-8")
    assert "created_at DATETIME" in sql
    assert "updated_at DATETIME" in sql
    assert "ON UPDATE CURRENT_TIMESTAMP" in sql


def test_ensure_script_backfills_column():
    """建表语句是 IF NOT EXISTS，已建表的环境靠 ensure 脚本幂等补列。"""
    script = (Path(__file__).resolve().parents[3] / "scripts" / "ensure_memory_relations.py").read_text(encoding="utf-8")
    assert "SHOW COLUMNS FROM memory_relations LIKE 'updated_at'" in script
    assert "ALTER TABLE memory_relations ADD COLUMN updated_at" in script
