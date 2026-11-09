"""学习计划草案状态机服务。

把"草案->确认->创建"从靠聊天关键词猜，改成服务端硬状态：
- create_draft 存草案对象（draft_id/revision/expires_at），旧 pending 草案标 superseded
- confirm_and_create 原子完成"校验 + 用 draft_data 创建计划 + 更新草案状态"，
  行锁幂等（重复确认返回同一个 plan_id），失败草案保持 pending 可重试

硬约束：正式计划只用 draft_data 创建，不接受模型重新传 title/items；
确认和创建是一个事务（_create_plan_records 只 flush，这里 commit）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import StudyPlan, StudyPlanDraft
from app.features.agent import date_guard
from app.features.p2.schemas import StudyPlanItemInput
from app.features.p2.study_plan import _create_plan_records

DRAFT_TTL_MINUTES = 30


def _utcnow() -> datetime:
    """naive UTC，对齐 StudyPlanDraft.created_at 口径。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@dataclass(frozen=True)
class ConfirmResult:
    plan_id: int | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.plan_id is not None


def create_draft(
    db: Session,
    student_id: int,
    chat_session_id: int | None,
    draft_data: dict,
    created_by: int | None,
    mode: str = "study",
) -> StudyPlanDraft:
    """存草案，旧 pending 草案标 superseded。"""
    db.query(StudyPlanDraft).filter(
        StudyPlanDraft.student_id == student_id,
        StudyPlanDraft.status == "pending",
    ).update({"status": "superseded"})
    draft = StudyPlanDraft(
        student_id=student_id,
        created_by=created_by,
        chat_session_id=chat_session_id,
        draft_data=draft_data,
        revision=1,
        status="pending",
        expires_at=_utcnow() + timedelta(minutes=DRAFT_TTL_MINUTES),
        mode=mode,
    )
    db.add(draft)
    db.flush()
    return draft


def get_draft(db: Session, draft_id: int, student_id: int) -> StudyPlanDraft | None:
    """查学生的草案（按 student_id 隔离，跨学生查不到）。"""
    return db.query(StudyPlanDraft).filter(
        StudyPlanDraft.id == draft_id,
        StudyPlanDraft.student_id == student_id,
    ).first()


def draft_is_expired(draft: StudyPlanDraft, now: datetime | None = None) -> bool:
    """服务端判定草案是否过期（expires_at 是无时区 UTC，统一在此比较，前端不猜时区）。"""
    if draft.expires_at is None:
        return False
    return (now or _utcnow()) > draft.expires_at


def confirm_and_create(
    db: Session,
    draft_id: int,
    revision: int,
    student_id: int,
    created_by: int | None,
) -> ConfirmResult:
    """原子完成：校验草案 -> 用 draft_data 创建计划 -> 草案标 created。

    行锁幂等：已 created 的草案再确认直接返回已建的 plan_id。
    失败不改草案状态（保持 pending 可重试），由调用方捕获异常。
    """
    draft = db.query(StudyPlanDraft).filter(
        StudyPlanDraft.id == draft_id,
        StudyPlanDraft.student_id == student_id,
    ).with_for_update().first()
    if not draft:
        return ConfirmResult(None, "草案不存在或无权访问")
    if draft.created_plan_id:  # 幂等：重复确认返回同一个 plan_id
        return ConfirmResult(draft.created_plan_id, None)
    if draft.revision != revision:
        return ConfirmResult(None, f"草案已修改，请确认最新版本(revision={draft.revision})")
    if draft.status == "superseded":
        return ConfirmResult(None, "已有更新的草案，请确认最新草案")
    if draft.expires_at and _utcnow() > draft.expires_at:
        return ConfirmResult(None, "草案已过期，请重新生成")

    # 用 draft_data 创建（不接受外部传参，防止用户确认 A 模型落库成 B）
    data = dict(draft.draft_data)
    # 服务端日期硬边界：确认前再次校正，保护部署前遗留草案与跨午夜确认（M0）
    data["planned_date"] = date_guard.normalize_planned_date(data.get("planned_date"))
    data["title"] = date_guard.sync_today_label_in_title(data.get("title", ""), data["planned_date"])
    draft.draft_data = data  # 校正后数据随本事务一起提交，卡片/正式计划/草案三处一致
    items = [StudyPlanItemInput(**item) for item in data.get("items", [])]
    # M2 C：确认时把 draft 中的 description/context_refs 一起传给正式计划，来源不丢失（方案 2.4.5.7）
    plan = _create_plan_records(
        db,
        student_id,
        data["title"],
        items,
        focus=data.get("focus"),
        planned_date=data["planned_date"],
        description=data.get("description"),
        context_refs=data.get("context_refs"),
        mode=getattr(draft, "mode", "study"),
        created_by=created_by,
    )
    draft.status = "created"
    draft.created_plan_id = plan.id
    db.commit()  # 原子：计划记录 + 草案状态一起提交
    db.refresh(plan)
    return ConfirmResult(plan.id, None)
