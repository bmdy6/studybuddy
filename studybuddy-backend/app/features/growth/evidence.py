from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.note import Note
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.user import User

from .facts import GrowthPeriod


class GrowthEvidence(BaseModel):
    student_id: int
    student_name: str
    period: GrowthPeriod
    period_start: str
    period_end: str
    confirmed_notes: list[dict[str, Any]] = Field(default_factory=list)
    recent_errors: list[dict[str, Any]] = Field(default_factory=list)
    completed_plan_items: list[dict[str, Any]] = Field(default_factory=list)
    exam_results: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return any(
            (
                self.confirmed_notes,
                self.recent_errors,
                self.completed_plan_items,
                self.exam_results,
            )
        )


def _period_bounds(period: GrowthPeriod, now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now if now.tzinfo else now.replace(tzinfo=zone)
    local_now = local_now.astimezone(zone)
    start_date = local_now.date() if period == "daily" else local_now.date() - timedelta(days=local_now.weekday())
    local_start = datetime.combine(start_date, time.min, tzinfo=zone)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = local_now.astimezone(timezone.utc).replace(tzinfo=None)
    return local_start, local_now, utc_start, utc_end


def collect_growth_evidence(
    db: Session,
    student_id: int,
    *,
    period: GrowthPeriod,
    now: datetime,
) -> GrowthEvidence:
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise ValueError("学生不存在")
    local_start, local_now, utc_start, utc_end = _period_bounds(period, now)

    notes = (
        db.query(Note)
        .filter(
            Note.student_id == student_id,
            Note.mode == "study",
            Note.status == "confirmed",
            Note.created_at >= utc_start,
            Note.created_at <= utc_end,
        )
        .order_by(Note.created_at.asc(), Note.id.asc())
        .limit(settings.WECHAT_GROWTH_EVIDENCE_LIMIT)
        .all()
    )
    errors = (
        db.query(ErrorBook)
        .filter(
            ErrorBook.student_id == student_id,
            ErrorBook.last_wrong_at >= utc_start,
            ErrorBook.last_wrong_at <= utc_end,
        )
        .order_by(ErrorBook.last_wrong_at.asc(), ErrorBook.id.asc())
        .limit(settings.WECHAT_GROWTH_EVIDENCE_LIMIT)
        .all()
    )
    completed_items = (
        db.query(StudyPlanItem, StudyPlan)
        .join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id)
        .filter(
            StudyPlan.student_id == student_id,
            StudyPlan.mode == "study",
            StudyPlanItem.status == "done",
            StudyPlanItem.completed_at >= utc_start,
            StudyPlanItem.completed_at <= utc_end,
        )
        .order_by(StudyPlanItem.completed_at.asc(), StudyPlanItem.id.asc())
        .limit(settings.WECHAT_GROWTH_EVIDENCE_LIMIT)
        .all()
    )
    exam_rows = (
        db.query(ExamRecord, Exam)
        .join(Exam, Exam.id == ExamRecord.exam_id)
        .filter(
            ExamRecord.student_id == student_id,
            ExamRecord.submitted_at >= utc_start,
            ExamRecord.submitted_at <= utc_end,
        )
        .order_by(ExamRecord.submitted_at.asc(), ExamRecord.id.asc())
        .limit(settings.WECHAT_GROWTH_EVIDENCE_LIMIT)
        .all()
    )
    return GrowthEvidence(
        student_id=student.id,
        student_name=student.display_name or student.username,
        period=period,
        period_start=local_start.isoformat(),
        period_end=local_now.isoformat(),
        confirmed_notes=[
            {
                "title": note.title,
                "subject": note.subject,
                "knowledge_tags": note.knowledge_tags or [],
            }
            for note in notes
        ],
        recent_errors=[
            {
                "knowledge_tags": error.knowledge_tags or [],
                "error_count": error.error_count,
                "last_wrong_at": error.last_wrong_at.isoformat(),
            }
            for error in errors
        ],
        completed_plan_items=[
            {
                "plan_title": plan.title,
                "item_title": item.title,
                "completed_at": item.completed_at.isoformat(),
            }
            for item, plan in completed_items
        ],
        exam_results=[
            {
                "exam_title": exam.title,
                "status": record.status,
                "total_score": str(record.total_score) if record.total_score is not None else None,
                "submitted_at": record.submitted_at.isoformat(),
            }
            for record, exam in exam_rows
        ],
    )
