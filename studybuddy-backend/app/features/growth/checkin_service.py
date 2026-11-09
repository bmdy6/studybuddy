"""每日对齐状态判断和幂等快捷选择写入。"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.daily_learning_record import DailyLearningRecord
from app.models.p2 import StudyPlan, StudyPlanItem
from .schemas.daily_checkin import DailyCheckinChoice, DailyCheckinStatus, CheckinChoiceKey
from . import daily_record_service as daily_learning_record_service


class CheckinAlreadyCompletedError(ValueError):
    """同一天已用另一选项完成对齐。"""


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def _todo_items(db: Session, student_id: int, target_date: date) -> list[StudyPlanItem]:
    return (
        db.query(StudyPlanItem)
        .join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id)
        .filter(
            StudyPlan.student_id == student_id,
            StudyPlan.mode == "study",
            StudyPlan.status == "active",
            StudyPlan.planned_date == target_date,
            StudyPlanItem.status == "todo",
        )
        .order_by(StudyPlanItem.sort_order.asc(), StudyPlanItem.id.asc())
        .all()
    )


def _pending_for_day(db: Session, student_id: int, target_date: date) -> list[dict[str, Any]]:
    record = daily_learning_record_service.get_by_date(db, student_id, target_date)
    if record is not None:
        snapshot = record.facts_snapshot or {}
        pending = snapshot.get("pending_tasks") or []
        if pending:
            return list(pending)
        # An existing, refreshed record with an empty pending list is authoritative.
        if record.evidence_hash or snapshot.get("period_start") is not None:
            return []
    return [{"item_title": item.title} for item in _todo_items(db, student_id, target_date)]


def _today_plan_summary(db: Session, student_id: int, target_date: date) -> tuple[int, int]:
    items = _todo_items(db, student_id, target_date)
    return len(items), sum(max(item.minutes, 0) for item in items)


def _unfinished_days(db: Session, student_id: int, target_date: date) -> int:
    count = 0
    cursor = target_date
    while True:
        pending = _pending_for_day(db, student_id, cursor)
        if not pending:
            return count
        count += 1
        cursor -= timedelta(days=1)
        if count >= 30:
            return count


def _choices(status: str) -> list[DailyCheckinChoice]:
    labels = {
        "follow_plan": "按今天计划开始",
        "adjust": "调整一下",
        "reduce": "少做一项",
    }
    keys: dict[str, tuple[CheckinChoiceKey, ...]] = {
        "yesterday_completed": ("follow_plan", "adjust"),
        "yesterday_incomplete": ("follow_plan", "adjust", "reduce"),
        "consecutive_incomplete": ("reduce", "adjust", "follow_plan"),
        "no_plan": ("adjust", "follow_plan"),
        "already_done": (),
    }
    return [DailyCheckinChoice(key=key, label=labels[key]) for key in keys[status]]


def _status_payload(record: DailyLearningRecord, status: str, unfinished_days: int, task_count: int, minutes: int) -> DailyCheckinStatus:
    messages = {
        "yesterday_completed": "昨天按计划完成得不错，今天继续从最重要的一项开始。",
        "yesterday_incomplete": "昨天还有任务没完成，今天一起把安排调得更合适。",
        "consecutive_incomplete": "这几天有任务没完成，今天先减一点量，稳稳开始。",
        "no_plan": "今天还没有安排好的学习计划，可以先一起定一个轻量目标。",
        "already_done": "今天的学习对齐已经完成，按当前安排继续就好。",
    }
    primary: CheckinChoiceKey | None = {
        "yesterday_completed": "follow_plan",
        "yesterday_incomplete": "follow_plan",
        "consecutive_incomplete": "reduce",
        "no_plan": "adjust",
        "already_done": None,
    }[status]
    choices = _choices(status)
    return DailyCheckinStatus(
        record_date=record.record_date,
        status=status, state=status, message=messages[status],
        task_count=task_count, estimated_minutes=minutes, unfinished_days=unfinished_days,
        primary_action=primary, primary_recommendation=primary, choices=choices,
        checkin_status=record.checkin_status, checkin_response=record.checkin_response,
        checked_in_at=record.checked_in_at,
    )


def get_status(db: Session, student_id: int, *, target_date: date | None = None) -> DailyCheckinStatus:
    target_date = target_date or local_today()
    record = daily_learning_record_service.get_or_create(db, student_id, target_date)
    if record.checkin_status is None:
        record.checkin_status = "pending"
        db.commit()
        db.refresh(record)
    task_count, minutes = _today_plan_summary(db, student_id, target_date)
    if record.checkin_status == "done":
        status = "already_done"
        unfinished_days = 0
    elif task_count == 0:
        status = "no_plan"
        unfinished_days = _unfinished_days(db, student_id, target_date - timedelta(days=1))
    else:
        unfinished_days = _unfinished_days(db, student_id, target_date - timedelta(days=1))
        status = "consecutive_incomplete" if unfinished_days >= 2 else ("yesterday_incomplete" if unfinished_days == 1 else "yesterday_completed")
    return _status_payload(record, status, unfinished_days, task_count, minutes)


def submit(db: Session, student_id: int, choice: CheckinChoiceKey, *, target_date: date | None = None) -> DailyCheckinStatus:
    target_date = target_date or local_today()
    record = daily_learning_record_service.get_or_create(db, student_id, target_date)
    # Conditional UPDATE is atomic on MySQL and also behaves correctly on SQLite tests:
    # exactly one concurrent caller can transition pending/null -> done.
    updated = (
        db.query(DailyLearningRecord)
        .filter(
            DailyLearningRecord.id == record.id,
            or_(DailyLearningRecord.checkin_status.is_(None), DailyLearningRecord.checkin_status == "pending"),
        )
        .update(
            {
                DailyLearningRecord.checkin_status: "done",
                DailyLearningRecord.checkin_response: choice,
                DailyLearningRecord.checked_in_at: datetime.now(timezone.utc).replace(tzinfo=None),
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    else:
        db.rollback()
        record = daily_learning_record_service.get_by_date(db, student_id, target_date)
        if record is None or record.checkin_response != choice:
            raise CheckinAlreadyCompletedError("今天已经完成过对齐")
    return get_status(db, student_id, target_date=target_date)
