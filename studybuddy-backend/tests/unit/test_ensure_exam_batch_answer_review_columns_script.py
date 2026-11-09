from pathlib import Path


def test_ensure_exam_batch_answer_review_columns_script_contains_expected_columns():
    script = Path("scripts/ensure_exam_batch_answer_review_columns.py").read_text(encoding="utf-8")

    assert "recognized_markdown" in script
    assert "answer_review_state" in script
    assert "answer_review_confirmed_at" in script
    assert "exam_batches" in script
    assert "ADD COLUMN" in script
    assert "SessionLocal" in script
    assert "sys.path.insert" in script
    assert "settings.database_url" not in script
