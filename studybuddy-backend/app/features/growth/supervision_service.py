from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.exam import Exam
from app.models.exam_assignment import ExamAssignment
from app.models.user import User
from .schemas.supervision import (
    SupervisionAssignmentItem,
    SupervisionReminderItem,
    SupervisionSummaryResponse,
    SupervisionSupportItem,
    SupervisionWeakPointItem,
    WeeklyReportDraft,
)
from app.features.note import service as note_service
from app.features.p2 import study_plan
from app.features.learning import map_service as learning_map_service  # learning 已迁 features，跨域用全路径（§1 单向）


SUPPORT_HEADING_RE = re.compile(r"^##\s*需要督促的地方\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)


def extract_support_section(content: str) -> str | None:
    match = SUPPORT_HEADING_RE.search(content or "")
    if not match:
        return None
    rest = content[match.end() :]
    next_heading = NEXT_HEADING_RE.search(rest)
    section = rest[: next_heading.start()] if next_heading else rest
    cleaned = "\n".join(line.strip() for line in section.strip().splitlines() if line.strip())
    return cleaned or None


def build_supervision_summary(
    db: Session,
    student_id: int,
    limit: int = 5,
) -> SupervisionSummaryResponse:
    student = db.get(User, student_id)
    reminders = _collect_reminders(db, student_id, limit)
    support_items = _collect_support_items(db, student_id, limit)
    weak_points = _collect_weak_points(db, student_id, limit)
    assignments = _collect_recent_assignments(db, student_id, limit)
    weekly_report = _build_weekly_report(reminders, support_items, weak_points, assignments)
    return SupervisionSummaryResponse(
        student_id=student_id,
        student_name=(student.display_name or student.username) if student else None,
        reminders=reminders,
        support_items=support_items,
        weak_points=weak_points,
        recent_assignments=assignments,
        weekly_report=weekly_report,
    )


def _collect_reminders(
    db: Session,
    student_id: int,
    limit: int,
) -> list[SupervisionReminderItem]:
    from app.models.user import User

    student = db.get(User, student_id)
    student_mode = getattr(student, "mode", "study") if student else "study"
    reminders = study_plan.list_due_study_plan_reminders(db, [student_id], limit=limit, mode=student_mode)
    return [
        SupervisionReminderItem(
            plan_id=item.plan_id,
            title=item.title,
            planned_date=item.planned_date,
            is_overdue=item.is_overdue,
            overdue_days=item.overdue_days,
            todo_count=item.todo_count,
            todo_minutes=item.todo_minutes,
            first_todo_title=item.first_todo_title,
            reminder_message=item.reminder_message,
        )
        for item in reminders[:limit]
    ]


def _collect_support_items(
    db: Session,
    student_id: int,
    limit: int,
) -> list[SupervisionSupportItem]:
    notes = note_service.list_notes(db, student_id, status="confirmed")
    items: list[SupervisionSupportItem] = []
    for note in notes:
        if note.category != "每日回顾" and note.source != "每日回顾":
            continue
        support = extract_support_section(note.content)
        if not support:
            continue
        items.append(
            SupervisionSupportItem(
                note_id=note.id,
                title=note.title,
                content=support,
                created_at=note.created_at,
            )
        )
        if len(items) >= limit:
            break
    return items


def _collect_weak_points(
    db: Session,
    student_id: int,
    limit: int,
) -> list[SupervisionWeakPointItem]:
    learning_map = learning_map_service.build_learning_map(db, student_id, limit=30)
    items: list[SupervisionWeakPointItem] = []
    for node in learning_map.nodes:
        if node.status != "weak":
            continue
        items.append(
            SupervisionWeakPointItem(
                tag=node.tag,
                status=node.status,
                error_count=node.error_count,
                last_wrong_at=node.last_wrong_at,
                next_action=node.next_actions[0] if node.next_actions else "先查看相关错题再决定下一步。",
            )
        )
        if len(items) >= limit:
            break
    return items


def _collect_recent_assignments(
    db: Session,
    student_id: int,
    limit: int,
) -> list[SupervisionAssignmentItem]:
    rows = (
        db.query(ExamAssignment, Exam)
        .join(Exam, Exam.id == ExamAssignment.exam_id)
        .filter(ExamAssignment.student_id == student_id, ExamAssignment.status != "cancelled")
        .order_by(ExamAssignment.created_at.desc(), ExamAssignment.id.desc())
        .limit(limit)
        .all()
    )
    return [
        SupervisionAssignmentItem(
            assignment_id=assignment.id,
            exam_id=assignment.exam_id,
            exam_title=exam.title,
            status=assignment.status,
            due_at=assignment.due_at.strftime("%Y-%m-%d %H:%M:%S") if assignment.due_at else None,
            note=assignment.note,
            created_at=assignment.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if assignment.created_at
            else "",
        )
        for assignment, exam in rows
    ]


def _build_weekly_report(
    reminders: list[SupervisionReminderItem],
    support_items: list[SupervisionSupportItem],
    weak_points: list[SupervisionWeakPointItem],
    assignments: list[SupervisionAssignmentItem],
) -> WeeklyReportDraft:
    highlights: list[str] = []
    suggestions: list[str] = []
    sources: list[str] = []
    if weak_points:
        top = weak_points[0]
        highlights.append(f"本周优先关注「{top.tag}」，错题累计 {top.error_count} 次。")
        suggestions.append(top.next_action)
        sources.append("学习地图")
    if reminders:
        first = reminders[0]
        highlights.append(f"还有学习计划「{first.title}」未完成，先做「{first.first_todo_title}」。")
        suggestions.append(first.reminder_message)
        sources.append("学习计划")
    if support_items:
        highlights.append(f"学生自己提到需要督促：{support_items[0].content}")
        suggestions.append("提醒时优先沿用学生自己的说法，避免变成命令式催促。")
        sources.append("每日回顾")
    if assignments:
        highlights.append(f"最近已分发「{assignments[0].exam_title}」，状态为 {assignments[0].status}。")
        sources.append("试卷分发")
    if not highlights:
        return WeeklyReportDraft(
            is_empty=True,
            summary="记录还不够，先让学生完成一次每日回顾、计划或错题练习。",
        )
    return WeeklyReportDraft(
        is_empty=False,
        summary="本草稿只基于已有错题、计划、每日回顾和分发记录生成，适合家长快速判断今天该提醒什么。",
        highlights=highlights,
        next_suggestions=list(dict.fromkeys(suggestions))[:5],
        sources=list(dict.fromkeys(sources)),
    )
