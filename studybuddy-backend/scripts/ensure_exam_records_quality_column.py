import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


def ensure_exam_records_quality_column(session_factory=SessionLocal) -> bool:
    """幂等：给 exam_records 加 suspected_low_quality 列（防敷衍门禁标记）。"""
    with session_factory() as db:
        cols = db.execute(text("SHOW COLUMNS FROM exam_records LIKE 'suspected_low_quality'")).first()
        if cols is not None:
            return False
        db.execute(
            text(
                "ALTER TABLE exam_records "
                "ADD COLUMN suspected_low_quality TINYINT NOT NULL DEFAULT 0 "
                "COMMENT '防敷衍门禁标记: 1=疑似敷衍/乱点/空提交' "
                "AFTER submitted_at"
            )
        )
        db.commit()
        return True


def main() -> None:
    added = ensure_exam_records_quality_column()
    if added:
        print("已为 exam_records 添加 suspected_low_quality 列")
    else:
        print("exam_records.suspected_low_quality 已存在，无需修改")


if __name__ == "__main__":
    main()
