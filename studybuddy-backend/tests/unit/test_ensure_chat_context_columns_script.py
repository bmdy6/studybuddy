from pathlib import Path


def test_ensure_chat_context_columns_script_contains_expected_columns():
    script = Path("scripts/ensure_chat_context_columns.py").read_text(encoding="utf-8")

    assert "context_summary" in script
    assert "context_summary_message_id" in script
    assert "chat_sessions" in script
    assert "ADD COLUMN" in script
    assert "SessionLocal" in script
    assert "sys.path.insert" in script


def test_chat_schema_contains_rolling_context_columns():
    schema = Path("sql/002_chat.sql").read_text(encoding="utf-8")

    assert "context_summary" in schema
    assert "context_summary_message_id" in schema
