#!/usr/bin/env python
"""修复协议错误的历史判分（P0）：用当前 grade()（normalize 索引/字母）重算 submitted 记录的客观题。

用法：
  python scripts/fix_protocol_error_records.py          # dry-run，只打印受影响记录数
  python scripts/fix_protocol_error_records.py --apply  # 实际更新并提交

说明：历史 AI 自练卷 correct_answer 存数字索引，旧判分比较失败导致正式 0 分；
grade() 已归一化，本脚本对存量数据重算（P0：错误正式状态修复）。
"""
import sys

sys.path.insert(0, ".")

from app.database import SessionLocal  # noqa: E402
from app.features.exams.grading_service import recalculate_submitted_records  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        changed_records, changed_answers = recalculate_submitted_records(db, apply=apply)
    finally:
        db.close()
    mode = "已更新" if apply else "dry-run（未更新）"
    print(f"P0 历史判分重算完成 [{mode}]：受影响 records={changed_records}，answers={changed_answers}")


if __name__ == "__main__":
    main()
