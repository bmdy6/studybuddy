"""派发学习计划站内提醒。

用法：
  PYTHONPATH=. .venv/bin/python scripts/dispatch_study_plan_reminders.py
  PYTHONPATH=. .venv/bin/python scripts/dispatch_study_plan_reminders.py --student-id 2 --limit 50

生产环境可放到宝塔计划任务或 cron，每天执行 1-3 次；通知表按计划和日期去重，重复执行不会重复打扰。
"""

import argparse
import json
import sys

from app.database import SessionLocal
from app.features.p2 import reminder_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="派发学习计划站内提醒")
    parser.add_argument("--student-id", type=int, action="append", help="只派发指定学生；可重复传多个")
    parser.add_argument("--limit", type=int, default=200, help="最多扫描的待提醒计划数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        if args.student_id:
            result = reminder_service.dispatch_study_plan_reminder_notifications(db, student_ids=args.student_id, limit=args.limit)
        else:
            result = reminder_service.dispatch_all_study_plan_reminder_notifications(db, limit=args.limit)
        print(
            json.dumps(
                {
                    "created_count": result.created_count,
                    "skipped_count": result.skipped_count,
                    "notification_ids": [item.id for item in result.notifications],
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
