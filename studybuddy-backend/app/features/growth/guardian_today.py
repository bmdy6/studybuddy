from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.utils.duration import parse_duration_minutes
from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from . import daily_record_service as daily_learning_record_service

from . import evidence

logger = logging.getLogger(__name__)


def _render_guardian_today_facts(
    *,
    duration_minutes: int,
    evidence: list[dict[str, Any]],
    pending_tasks: list[dict[str, Any]],
) -> str:
    """确定性渲染家长今日摘要文本，格式与定时推送 fallback 保持一致。

    事实来源统一为每日记录的 facts_snapshot；不重新查证据库。
    计划完成优先展示，否则依次展示笔记/错题/试卷；机器素材不在此处升级展示。
    """
    completed = [item for item in evidence if item.get("source_type") == "study_plan_item"]
    notes = [item for item in evidence if item.get("source_type") == "note"]
    errors = [item for item in evidence if item.get("source_type") == "error_book"]
    exams = [item for item in evidence if item.get("source_type") == "exam_record"]
    has_evidence = bool(completed or notes or errors or exams)

    if not duration_minutes and not has_evidence and not pending_tasks:
        return "今天还没有学习记录，学习时长也未记录。"

    sections = [f"今天学习 {duration_minutes} 分钟。" if duration_minutes else "学习时长暂未记录。"]
    if completed:
        completed_lines = [
            f"- {item.get('plan_title') or '学习计划'}：{item.get('title') or ''}"
            for item in completed
        ]
        sections.append("完成：\n" + "\n".join(completed_lines))
    elif has_evidence:
        records = [
            *(f"- 笔记：{item.get('title') or ''}" for item in notes),
            *(
                f"- 错题：{'、'.join(item.get('knowledge_tags') or []) or '未标知识点'}"
                for item in errors
            ),
            *(f"- 试卷：{item.get('title') or ''}" for item in exams),
        ]
        sections.append("今天记录：\n" + "\n".join(records))
    else:
        sections.append("今天暂未记录具体学习内容。")

    if pending_tasks:
        pending_titles = "、".join(item.get("item_title") or "" for item in pending_tasks if item.get("item_title"))
        sections.append(f"还有 {len(pending_tasks)} 项未完成：{pending_titles}。")
    return "\n\n".join(sections)


def build_guardian_today_learning_summary(
    db: Session,
    student_id: int,
    *,
    now: datetime | None = None,
) -> str:
    """家长主动查询今日学情时返回与定时推送同源的确定性事实文本。

    优先读已落库的当日学习记录（与定时推送 refresh 写入同一份 facts_snapshot）；
    若当日记录尚未生成（定时 refresh 未跑或失败），现场用同一套 aggregate_daily_facts
    聚合事实兜底，保证主动查询和定时推送读到的都是同一份事实口径，不复制第二套
    证据查询。LLM 摘要不在主动查询路径生成（即时回复、省 token、不幻觉），只读确定性
    事实；预计分钟永不冒充实际时长。聚合失败时回退到直接查证据的确定性兜底。
    """
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now or datetime.now(zone)
    local_now = local_now if local_now.tzinfo else local_now.replace(tzinfo=zone)
    local_now = local_now.astimezone(zone)

    try:
        record = daily_learning_record_service.get_by_date(
            db,
            student_id=student_id,
            record_date=local_now.date(),
        )
        if record is not None and record.facts_snapshot:
            facts = record.facts_snapshot
        else:
            # 当日记录尚未由定时 refresh 生成时，现场用同源 aggregate_daily_facts 聚合，
            # 不落库、不调 LLM，避免主动查询副作用污染摘要或重复造查询。
            facts = daily_learning_record_service.aggregate_daily_facts(
                db,
                student_id,
                local_now.date(),
                now=local_now,
            )
        return _render_guardian_today_facts(
            duration_minutes=int(facts.get("self_reported_duration_minutes") or 0),
            evidence=list(facts.get("evidence") or []),
            pending_tasks=list(facts.get("pending_tasks") or []),
        )
    except Exception:
        logger.warning("guardian today query daily record read failed", exc_info=True)
        # 落到下面确定性兜底，仍只读真实证据，不幻觉。

    return _guardian_today_learning_summary_direct_fallback(db, student_id, now=local_now)


def _guardian_today_learning_summary_direct_fallback(
    db: Session,
    student_id: int,
    *,
    now: datetime,
) -> str:
    """refresh 失败时的确定性兜底：直接查证据库，渲染格式与主路径一致。"""
    _, _, utc_start, utc_end = evidence._period_bounds("daily", now)
    growth_evidence = evidence.collect_growth_evidence(db, student_id, period="daily", now=now)

    duration_feedback = (
        db.query(LearningFeedback)
        .filter(
            LearningFeedback.student_id == student_id,
            LearningFeedback.feedback_type == "duration",
            LearningFeedback.created_at >= utc_start,
            LearningFeedback.created_at <= utc_end,
        )
        .all()
    )
    duration_minutes = sum(parse_duration_minutes(item.content) for item in duration_feedback)
    pending_items = (
        db.query(StudyPlanItem, StudyPlan)
        .join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id)
        .filter(
            StudyPlan.student_id == student_id,
            StudyPlan.mode == "study",
            StudyPlan.planned_date == now.date(),
            StudyPlan.status == "active",
            StudyPlanItem.status == "todo",
        )
        .order_by(StudyPlanItem.sort_order.asc(), StudyPlanItem.id.asc())
        .all()
    )

    # 转成与主路径一致的 facts dict 形状，复用 _render_guardian_today_facts 渲染，
    # 消除兜底路径与主路径的内联渲染重复（空态/分组/文案由 _render 统一处理）。
    evidence_items = [
        *({"source_type": "study_plan_item", "plan_title": item["plan_title"], "title": item["item_title"]} for item in growth_evidence.completed_plan_items),
        *({"source_type": "note", "title": item["title"]} for item in growth_evidence.confirmed_notes),
        *({"source_type": "error_book", "knowledge_tags": item["knowledge_tags"]} for item in growth_evidence.recent_errors),
        *({"source_type": "exam_record", "title": item["exam_title"]} for item in growth_evidence.exam_results),
    ]
    pending_tasks = [{"item_title": item.title} for item, _plan in pending_items]
    return _render_guardian_today_facts(
        duration_minutes=duration_minutes,
        evidence=evidence_items,
        pending_tasks=pending_tasks,
    )
