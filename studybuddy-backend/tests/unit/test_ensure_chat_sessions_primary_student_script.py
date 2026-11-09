"""ensure_chat_sessions_primary_student_id.py 脚本结构测试。

参考 tests/unit/test_ensure_chat_context_columns_script.py 的做法：
校验脚本包含必要的列/索引/表名声明，避免后续误删关键字段。
"""

from pathlib import Path


def test_ensure_chat_sessions_primary_student_script_contains_expected_tokens():
    script = Path("scripts/ensure_chat_sessions_primary_student_id.py").read_text(encoding="utf-8")

    assert "chat_sessions" in script
    assert "primary_student_id" in script
    assert "uk_chat_sessions_primary_student" in script
    assert "ADD COLUMN" in script
    # 单列唯一索引已废弃：本脚本只保证列存在，不再创建旧索引（复合唯一由 ensure_chat_session_mode.py 负责）
    assert "ADD UNIQUE KEY" not in script
    assert "不再创建" in script
    assert "SessionLocal" in script
    assert "sys.path.insert" in script


def test_chat_sessions_migration_sql_contains_primary_student_column_and_unique_index():
    schema = Path("sql/019_chat_sessions_primary_student.sql").read_text(encoding="utf-8")

    assert "primary_student_id" in schema
    assert "uk_chat_sessions_primary_student" in schema
    assert "UNIQUE KEY" in schema
    assert "information_schema" in schema  # 幂等校验
