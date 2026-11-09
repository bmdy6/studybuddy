"""刷新每日学习记录并收口跨日记录。"""

import argparse
import asyncio
import json
import sys
from datetime import date

from app.database import SessionLocal
from app.features.growth import daily_record_service as daily_learning_record_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新每日学习记录并收口跨日记录")
    parser.add_argument("--student-id", type=int, action="append", help="只刷新指定学生；可重复传多个")
    parser.add_argument("--date", type=date.fromisoformat, help="刷新指定本地日期，默认今天")
    return parser.parse_args()


def run_refresh(db, *, student_ids: list[int] | None, record_date: date | None) -> dict[str, int]:
    return asyncio.run(
        daily_learning_record_service.refresh_students(
            db,
            student_ids=student_ids,
            record_date=record_date,
        )
    )


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        print(json.dumps(run_refresh(db, student_ids=args.student_id, record_date=args.date), ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
