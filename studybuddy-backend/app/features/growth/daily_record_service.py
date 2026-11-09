"""每日学习记录服务：内部幂等 get_or_create + 只读查询（spec 3.1/4.1）。

本 PR 只交付事实容器和查询。证据聚合、evidence_hash 计算、AI 摘要生成、跨日
finalize 均不在本 PR 范围（PR-03/04/13），由后续 PR 通过 refresh 入口扩展本 service。

写入边界（spec 5.1）：只有 service 层内部可写入，不开放前端任意覆盖事实快照。
"""

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.utils.duration import parse_duration_minutes
from app.models.daily_learning_record import DailyLearningRecord
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.material import Material
from app.models.note import Note
from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem, StudyPlanItemAttempt
from app.models.user import User
from . import daily_summary_service

logger = logging.getLogger(__name__)


def aggregate_daily_facts(db: Session, student_id: int, record_date: date, *, now: datetime | None = None) -> dict[str, Any]:
    """Build the deterministic, source-addressable facts snapshot for one student/day."""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_start = datetime.combine(record_date, time.min, tzinfo=zone)
    local_end = (now or datetime.now(zone)).astimezone(zone)
    if local_end.date() != record_date:
        local_end = datetime.combine(record_date, time.max, tzinfo=zone)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)
    evidence: list[dict[str, Any]] = []
    def add(item: dict[str, Any]) -> None:
        if not any((x["source_type"], x["source_id"]) == (item["source_type"], item["source_id"]) for x in evidence):
            evidence.append(item)
    # P0 修复：批量关联每个计划项最新的 passed Attempt 证据（一次 IN 查询防 N+1）
    done_items = db.query(StudyPlanItem, StudyPlan).join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id).filter(StudyPlan.student_id == student_id, StudyPlan.mode == "study", StudyPlanItem.status == "done", StudyPlanItem.completed_at >= utc_start, StudyPlanItem.completed_at <= utc_end).order_by(StudyPlanItem.id.asc()).all()
    if done_items:
        item_ids = [item.id for item, _ in done_items]
        passed_attempts = db.query(StudyPlanItemAttempt).filter(
            StudyPlanItemAttempt.plan_item_id.in_(item_ids),
            StudyPlanItemAttempt.assessment == "passed",
        ).order_by(StudyPlanItemAttempt.id.asc()).all()
        latest_by_item: dict[int, str | None] = {}
        for a in passed_attempts:  # 升序遍历，后者覆盖 = 取最新
            latest_by_item[a.plan_item_id] = a.evidence_summary
    else:
        latest_by_item = {}
    for item, plan in done_items:
        evidence_summary = latest_by_item.get(item.id)
        entry = {"source_type": "study_plan_item", "source_id": item.id, "version": 1, "tier": "self_reported", "title": item.title, "plan_title": plan.title, "completed_at": item.completed_at.isoformat()}
        if getattr(item, "related_tags", None):
            entry["knowledge_tags"] = item.related_tags or []
        if evidence_summary and evidence_summary.strip():
            entry["evidence_summary"] = evidence_summary.strip()  # 历史无 Attempt 时省略，不编造
        add(entry)
    for record, exam in db.query(ExamRecord, Exam).join(Exam, Exam.id == ExamRecord.exam_id).filter(ExamRecord.student_id == student_id, ExamRecord.status.in_(["submitted", "graded"]), ExamRecord.submitted_at >= utc_start, ExamRecord.submitted_at <= utc_end).order_by(ExamRecord.id.asc()).all():
        add({"source_type": "exam_record", "source_id": record.id, "version": 1, "tier": "verified", "title": exam.title, "status": record.status, "submitted_at": record.submitted_at.isoformat()})
    for note in db.query(Note).filter(Note.student_id == student_id, Note.mode == "study", Note.status == "confirmed", Note.created_at >= utc_start, Note.created_at <= utc_end).order_by(Note.id.asc()).all():
        entry = {"source_type": "note", "source_id": note.id, "version": 1, "tier": "verified", "title": note.title, "subject": note.subject}
        if getattr(note, "knowledge_tags", None):
            entry["knowledge_tags"] = note.knowledge_tags or []
        add(entry)
    for error in db.query(ErrorBook).filter(ErrorBook.student_id == student_id, ErrorBook.last_wrong_at >= utc_start, ErrorBook.last_wrong_at <= utc_end).order_by(ErrorBook.id.asc()).all():
        add({"source_type": "error_book", "source_id": error.id, "version": 1, "tier": "verified", "title": "错题复练", "knowledge_tags": error.knowledge_tags or [], "last_wrong_at": error.last_wrong_at.isoformat()})
    owner_filter = or_(Material.student_id == student_id, and_(Material.student_id.is_(None), Material.uploaded_by == student_id))
    for material in db.query(Material).filter(owner_filter, Material.mode == "study", Material.auto_ready.is_(True), Material.recognized_at >= utc_start, Material.recognized_at <= utc_end).order_by(Material.id.asc()).all():
        text = material.confirmed_markdown or material.recognized_markdown or material.raw_text
        if text and text.strip():
            entry = {"source_type": "material", "source_id": material.id, "version": 1, "tier": "machine_extracted", "title": material.name, "provider": material.recognition_provider, "confidence": material.recognition_confidence, "uncertain_points": material.uncertain_points or []}
            if getattr(material, "knowledge_tags", None):
                entry["knowledge_tags"] = material.knowledge_tags or []
            add(entry)
    duration = sum(parse_duration_minutes(row.content) for row in db.query(LearningFeedback).filter(LearningFeedback.student_id == student_id, LearningFeedback.feedback_type == "duration", LearningFeedback.created_at >= utc_start, LearningFeedback.created_at <= utc_end).all())
    pending = [{"plan_title": plan.title, "item_title": item.title} for item, plan in db.query(StudyPlanItem, StudyPlan).join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id).filter(StudyPlan.student_id == student_id, StudyPlan.mode == "study", StudyPlan.status == "active", StudyPlan.planned_date == record_date, StudyPlanItem.status == "todo").order_by(StudyPlanItem.sort_order.asc(), StudyPlanItem.id.asc()).all()]
    evidence.sort(key=lambda x: (x["source_type"], x["source_id"], x["version"]))
    return {"student_id": student_id, "record_date": record_date.isoformat(), "period_start": local_start.isoformat(), "period_end": local_end.isoformat(), "timezone": settings.WECHAT_TIMEZONE, "evidence": evidence, "pending_tasks": pending, "self_reported_duration_minutes": duration, "has_verified_evidence": any(x["tier"] == "verified" for x in evidence)}


def evidence_hash(snapshot: dict[str, Any]) -> str:
    payload = {k: v for k, v in snapshot.items() if k not in {"period_end"}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _empty_facts_snapshot(student_id: int, record_date: date) -> dict[str, Any]:
    """构建 spec 3.2 空记录骨架。

    evidence/pending_tasks 为空，has_verified_evidence=False；timezone 仅作审计
    快照，来自服务端 settings.WECHAT_TIMEZONE，不接受客户端覆盖。
    period_start/end 暂留占位，由 PR-03 证据聚合填充真实窗口。
    """
    return {
        "student_id": student_id,
        "record_date": record_date.isoformat(),
        "period_start": None,
        "period_end": None,
        "timezone": settings.WECHAT_TIMEZONE,
        "evidence": [],
        "pending_tasks": [],
        "self_reported_duration_minutes": 0,
        "has_verified_evidence": False,
    }


def get_or_create(db: Session, student_id: int, record_date: date) -> DailyLearningRecord:
    """幂等获取或创建某学生某天的记录（spec 4.1 get_or_create_today 核心）。

    同一天多次调用返回同一条，依赖 UNIQUE(student_id, mode, record_date)。
    证据聚合与摘要生成不在本方法职责内，由 refresh 入口（PR-03/04）单独触发。
    """
    student = db.get(User, student_id)
    if student is None or student.role != "student":
        raise ValueError("每日学习记录只能归属于学生账号")

    existing = get_by_date(db, student_id=student_id, record_date=record_date)
    if existing is not None:
        return existing
    record = DailyLearningRecord(
        student_id=student_id,
        record_date=record_date,
        facts_snapshot=_empty_facts_snapshot(student_id, record_date),
        generation_status="pending",
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = get_by_date(db, student_id=student_id, record_date=record_date)
        if winner is None:
            raise
        return winner
    db.refresh(record)
    return record


def get_by_date(db: Session, student_id: int, record_date: date) -> DailyLearningRecord | None:
    """按学生 + 日期精确查询单条记录，未命中返回 None。"""
    return (
        db.query(DailyLearningRecord)
        .filter(
            DailyLearningRecord.student_id == student_id,
            DailyLearningRecord.record_date == record_date,
        )
        .first()
    )


def list_by_range(
    db: Session, student_id: int, start_date: date, end_date: date
) -> list[DailyLearningRecord]:
    """按学生 + 日期范围查询，按 record_date 升序。"""
    return (
        db.query(DailyLearningRecord)
        .filter(
            DailyLearningRecord.student_id == student_id,
            DailyLearningRecord.record_date >= start_date,
            DailyLearningRecord.record_date <= end_date,
        )
        .order_by(DailyLearningRecord.record_date.asc())
        .all()
    )


def _compact_context_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _unique_context_items(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("plan_title") or ""), str(item.get("item_title") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def build_agent_context(
    db: Session,
    student_id: int,
    *,
    now: datetime | None = None,
    max_chars: int = 1500,
) -> str:
    """构建学生 Agent 的每日记忆片段，不创建记录也不修改任何业务状态。

    只读取昨天的日报、今天的已确认计划和最近七天的事实趋势。日报摘要与事实
    分区标明来源，避免把 AI 表述误当成真实证据；任一读取异常都由调用方安全跳过。
    """
    if max_chars <= 0:
        return ""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now or datetime.now(zone)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=zone)
    else:
        local_now = local_now.astimezone(zone)
    today = local_now.date()
    yesterday = today - timedelta(days=1)

    yesterday_record = get_by_date(db, student_id=student_id, record_date=yesterday)
    today_plan_rows = (
        db.query(StudyPlan, StudyPlanItem)
        .join(StudyPlanItem, StudyPlanItem.plan_id == StudyPlan.id)
        .filter(
            StudyPlan.student_id == student_id,
            StudyPlan.status == "active",
            StudyPlan.planned_date == today,
            StudyPlanItem.status.in_(["todo", "done"]),
        )
        .order_by(StudyPlan.id.asc(), StudyPlanItem.sort_order.asc(), StudyPlanItem.id.asc())
        .limit(8)
        .all()
    )
    recent_records = list_by_range(
        db,
        student_id=student_id,
        start_date=today - timedelta(days=6),
        end_date=today,
    )

    sections: list[str] = []
    if yesterday_record:
        snapshot = yesterday_record.facts_snapshot or {}
        pending = _unique_context_items(snapshot.get("pending_tasks") or [], limit=5)
        facts: list[str] = []
        evidence = snapshot.get("evidence") or []
        evidence_titles = _unique_context_items(
            [{"item_title": item.get("title")} for item in evidence if isinstance(item, dict)],
            limit=5,
        )
        if evidence_titles:
            facts.append("已记录事实：" + "、".join(_compact_context_text(item["item_title"], 80) for item in evidence_titles))
        if pending:
            facts.append("未完成任务：" + "、".join(_compact_context_text(item["item_title"], 80) for item in pending))
        if snapshot.get("self_reported_duration_minutes"):
            facts.append(f"自报学习时长：{snapshot['self_reported_duration_minutes']} 分钟")
        if facts:
            sections.append(f"事实区（日期={yesterday.isoformat()}）：" + "；".join(facts))
        summary = _compact_context_text(yesterday_record.summary_text, 420)
        if summary:
            source = yesterday_record.summary_source or "unknown"
            summary_label = "AI摘要区" if source == "ai" else "摘要区"
            sections.append(f"{summary_label}（日期={yesterday.isoformat()}，来源={source}，仅作参考）：{summary}")

    today_tasks: list[str] = []
    seen_today: set[tuple[int, int]] = set()
    for plan, item in today_plan_rows:
        key = (plan.id, item.id)
        if key in seen_today:
            continue
        seen_today.add(key)
        title = _compact_context_text(item.title, 80)
        if title:
            status = "已完成" if item.status == "done" else "待完成"
            today_tasks.append(f"{_compact_context_text(plan.title, 60)}：{title}（{status}）")
    if today_tasks:
        sections.append(f"今日已确认计划（日期={today.isoformat()}）：" + "、".join(today_tasks[:5]))

    active_days = sum(
        bool((record.facts_snapshot or {}).get("evidence") or (record.facts_snapshot or {}).get("self_reported_duration_minutes"))
        for record in recent_records
    )
    repeated_pending: dict[str, int] = {}
    for record in recent_records:
        for item in _unique_context_items((record.facts_snapshot or {}).get("pending_tasks") or [], limit=8):
            title = _compact_context_text(item.get("item_title"), 80)
            if title:
                repeated_pending[title] = repeated_pending.get(title, 0) + 1
    trends = [title for title, count in repeated_pending.items() if count >= 2][:3]
    trend_items = [f"近7天有真实记录 {active_days} 天"] if active_days else []
    if trends:
        trend_items.append("重复未完成任务：" + "、".join(trends))
    if trend_items:
        sections.append("近期7天事实趋势：" + "；".join(trend_items))

    if not sections:
        return ""
    header = "[每日学习记录]"
    footer = (
        "AI摘要不是新的真实证据；如与历史压缩摘要重复，以本节日报版本为准；"
        "不要把计划完成说成已掌握，也不要补写不存在的日期、时长或进步。"
    )
    available = max_chars - len(header) - len(footer) - 2
    if available <= 0:
        return _compact_context_text(header, max_chars)
    selected: list[str] = []
    used = 0
    for section in sections:
        remaining = available - used - (1 if selected else 0)
        if remaining <= 0:
            break
        selected.append(_compact_context_text(section, remaining))
        used += len(selected[-1]) + (1 if len(selected) > 1 else 0)
    if not selected:
        return ""
    return header + "\n" + "\n".join(selected) + "\n" + footer


def _deterministic_summary(facts: dict[str, Any]) -> str:
    return daily_summary_service.deterministic_summary(facts)


def _local_now(now: datetime | None = None) -> datetime:
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    current = now or datetime.now(zone)
    return (current if current.tzinfo else current.replace(tzinfo=zone)).astimezone(zone)


async def _refresh_and_finalize_before(
    db: Session,
    student_id: int,
    record_date: date,
    *,
    now: datetime,
    finalized_at: datetime,
) -> int:
    records = (
        db.query(DailyLearningRecord)
        .filter(
            DailyLearningRecord.student_id == student_id,
            DailyLearningRecord.record_date < record_date,
            DailyLearningRecord.finalized_at.is_(None),
        )
        .order_by(DailyLearningRecord.record_date.asc())
        .all()
    )
    record_dates = [row.record_date for row in records]
    for previous_date in record_dates:
        await refresh(db, student_id, previous_date, now=now)
        record = get_by_date(db, student_id=student_id, record_date=previous_date)
        if record is None:
            continue
        record.finalized_at = finalized_at
        db.commit()
    return len(record_dates)


async def refresh_students(
    db: Session,
    *,
    student_ids: list[int] | None = None,
    record_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Refresh one date for selected/all students and close older open records."""
    local_now = _local_now(now)
    target_date = record_date or local_now.date()
    ids = student_ids or [
        row.id for row in db.query(User.id).filter(User.role == "student").order_by(User.id.asc()).all()
    ]
    result = {"processed": 0, "skipped": 0, "failed": 0}
    finalized_at = local_now.astimezone(timezone.utc).replace(tzinfo=None)
    for student_id in dict.fromkeys(ids):
        try:
            await _refresh_and_finalize_before(
                db,
                student_id,
                target_date,
                now=local_now,
                finalized_at=finalized_at,
            )
            before = get_by_date(db, student_id=student_id, record_date=target_date)
            before_hash = before.evidence_hash if before else None
            before_summary = before.summary_text if before else None
            await refresh(db, student_id, target_date, now=local_now)
            after = get_by_date(db, student_id=student_id, record_date=target_date)
            if before and after and before_hash == after.evidence_hash and before_summary == after.summary_text:
                result["skipped"] += 1
            else:
                result["processed"] += 1
        except Exception as exc:  # noqa: BLE001 - isolate one student in scheduled runs
            db.rollback()
            result["failed"] += 1
            logger.exception("daily record refresh failed for student=%s date=%s: %s", student_id, target_date, exc)
    return result


async def refresh(
    db: Session,
    student_id: int,
    record_date: date,
    *,
    now: datetime | None = None,
) -> DailyLearningRecord:
    """聚合事实并幂等生成同日摘要；旧摘要永远不作为事实输入。"""
    facts = aggregate_daily_facts(db, student_id, record_date, now=now)
    current_hash = evidence_hash(facts)
    record = get_or_create(db, student_id, record_date)
    if record.evidence_hash == current_hash and record.summary_text:
        return record

    record.facts_snapshot = facts
    record.evidence_hash = current_hash
    summary = ""
    if daily_summary_service.has_learning_facts(facts):
        record.generation_status = "generating"
        db.commit()
        try:
            summary = (await daily_summary_service.generate_summary(facts)).strip()
        except Exception as exc:  # noqa: BLE001 - LLM failure must degrade to facts
            logger.warning("daily summary generation failed for student=%s date=%s: %s", student_id, record_date, exc)
    if summary:
        record.summary_text = summary
        record.summary_source = "ai"
    else:
        record.summary_text = _deterministic_summary(facts)
        record.summary_source = "deterministic"
    record.generation_status = "ready"
    record.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(record)
    return record
