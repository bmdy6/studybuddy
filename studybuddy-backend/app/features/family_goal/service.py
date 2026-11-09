"""家庭目标与任务激励服务。

一条闭环：目标 -> 任务 -> 任务实例 -> 图片证据 -> 奖励记录。

权限职责划分：本模块提供 `assert_can_access_student`，浏览器入口（JWT）在 router 里
先解析 student_id 再调它；内部集成入口（X-Internal-Token）由 token 本身背书，直接传
显式 student_id，不做「猜当前孩子」。

金额规则：任务级优先，为空继承目标级；创建任务时两级都为空 -> 422（打完卡没有金额
等于没有激励）。确认后金额进 occurrence 快照，改任务金额不影响历史。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import (
    FAMILY_EVIDENCE_MAX_COUNT,
    FAMILY_PENDING_LIST_DEFAULT_LIMIT,
    FAMILY_REWARD_RECORD_DEFAULT_LIMIT,
)
from app.core.auth import access_service
from app.models.family_goal import (
    FamilyGoal,
    FamilyGoalTask,
    FamilyRewardRecord,
    FamilyTaskEvidence,
    FamilyTaskOccurrence,
)
from app.models.user import User
from app.utils.cos import build_public_url

logger = logging.getLogger(__name__)

CREATOR_ROLE_BY_USER_ROLE = {"student": "student", "teacher": "parent"}
VALID_REPEAT_TYPES = {"once", "daily"}
SUBMITTABLE_STATUSES = {"pending", "rejected"}
# DECIMAL(10,2) 上限，超过会静默截断，提前拦住
MAX_REWARD_AMOUNT = Decimal("99999999.99")


class FamilyGoalError(Exception):
    """业务校验失败：参数/状态/权限。router 按 status_code 转 HTTP 响应。"""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def today_in_app_timezone() -> date:
    """按业务时区取「今天」，不用服务器本地时区（部署机与用户时区未必一致）。"""
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def _now_utc() -> datetime:
    """业务时间戳统一写 naive UTC（与 LearningFeedback 等既有表口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _require_text(value: str | None, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise FamilyGoalError(f"{field}不能为空")
    return text


def _amount_str(amount: Decimal | None) -> str | None:
    return f"{amount:.2f}" if amount is not None else None


def _validate_amount(amount: Decimal | None, field: str = "奖励金额") -> Decimal | None:
    if amount is None:
        return None
    if amount < 0:
        raise FamilyGoalError(f"{field}不能为负数")
    if amount > MAX_REWARD_AMOUNT:
        raise FamilyGoalError(f"{field}不能超过 {MAX_REWARD_AMOUNT}")
    return amount.quantize(Decimal("0.01"))


def parse_amount(value: str | Decimal | None, field: str = "奖励金额") -> Decimal | None:
    """接口层传字符串（"5" / "5.5"），统一成两位小数 Decimal。"""
    if value is None or not str(value).strip():
        return None
    try:
        return _validate_amount(Decimal(str(value).strip()), field)
    except InvalidOperation:
        raise FamilyGoalError(f"{field}格式不正确") from None


def assert_can_access_student(db: Session, *, user: User, student_id: int) -> None:
    """学生只能访问自己；家长必须是通过 teacher_students 绑定的孩子。"""
    if user.role == "student":
        if student_id != user.id:
            raise FamilyGoalError("只能访问自己的数据", 403)
        return
    if not access_service.teacher_can_access_student(db, user.id, student_id):
        raise FamilyGoalError("无权访问该学生", 403)


def creator_role_of(user: User) -> str:
    role = CREATOR_ROLE_BY_USER_ROLE.get(user.role)
    if role is None:
        raise FamilyGoalError("当前角色不能创建家庭目标", 403)
    return role


def resolve_reward_amount(task: FamilyGoalTask, goal: FamilyGoal) -> Decimal | None:
    """任务级优先，为空继承目标级。"""
    return task.reward_amount if task.reward_amount is not None else goal.reward_amount


# ---------------- 目标与任务 ----------------


def create_goal(
    db: Session,
    *,
    student_id: int,
    created_by: int | None,
    creator_role: str,
    title: str,
    description: str | None = None,
    reward_amount: Decimal | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    mode: str = "study",
) -> FamilyGoal:
    if creator_role not in ("student", "parent"):
        raise FamilyGoalError("creator_role 只能是 student 或 parent")
    if start_date and end_date and end_date < start_date:
        raise FamilyGoalError("结束日期不能早于开始日期")
    goal = FamilyGoal(
        student_id=student_id,
        mode=mode,
        title=_require_text(title, "目标标题")[:128],
        description=(description or "").strip() or None,
        reward_amount=_validate_amount(reward_amount),
        created_by=created_by,
        creator_role=creator_role,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def list_goals(db: Session, *, student_id: int, include_archived: bool = False) -> list[FamilyGoal]:
    query = db.query(FamilyGoal).filter(FamilyGoal.student_id == student_id)
    if not include_archived:
        query = query.filter(FamilyGoal.status != "archived")
    return query.order_by(FamilyGoal.status.asc(), FamilyGoal.id.desc()).all()


def get_goal(db: Session, *, goal_id: int) -> FamilyGoal:
    goal = db.get(FamilyGoal, goal_id)
    if goal is None:
        raise FamilyGoalError("目标不存在", 404)
    return goal


def update_goal(
    db: Session,
    *,
    goal_id: int,
    title: str | None = None,
    description: str | None = None,
    reward_amount: Decimal | None = None,
    status: str | None = None,
) -> FamilyGoal:
    goal = get_goal(db, goal_id=goal_id)
    if title is not None:
        goal.title = _require_text(title, "目标标题")[:128]
    if description is not None:
        goal.description = description.strip() or None
    if reward_amount is not None:
        goal.reward_amount = _validate_amount(reward_amount)
    if status is not None:
        if status not in ("active", "completed", "archived"):
            raise FamilyGoalError("目标状态不合法")
        goal.status = status
    db.commit()
    db.refresh(goal)
    return goal


def create_task(
    db: Session,
    *,
    goal_id: int,
    student_id: int,
    created_by: int | None,
    title: str,
    description: str | None = None,
    repeat_type: str = "once",
    reward_amount: Decimal | None = None,
    sort_order: int = 0,
) -> FamilyGoalTask:
    goal = get_goal(db, goal_id=goal_id)
    if goal.student_id != student_id:
        raise FamilyGoalError("任务与目标不属于同一学生", 403)
    if repeat_type not in VALID_REPEAT_TYPES:
        raise FamilyGoalError("repeat_type 只能是 once 或 daily")
    reward_amount = _validate_amount(reward_amount)
    if reward_amount is None and goal.reward_amount is None:
        raise FamilyGoalError("任务需要奖励金额（任务级或目标级至少填一个）")

    task = FamilyGoalTask(
        goal_id=goal.id,
        student_id=student_id,
        mode=goal.mode,
        title=_require_text(title, "任务标题")[:160],
        description=(description or "").strip() or None,
        repeat_type=repeat_type,
        reward_amount=reward_amount,
        sort_order=sort_order,
        created_by=created_by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 一次性任务：建好即产生当天实例，孩子打开今天页立刻能看到。
    # 每日任务：等首次查今天任务时惰性生成（ensure_occurrences），不引定时任务。
    if task.repeat_type == "once":
        ensure_occurrences(db, student_id=student_id, on_date=today_in_app_timezone(), task_ids=[task.id])
    return task


def list_tasks(db: Session, *, goal_id: int, include_archived: bool = False) -> list[FamilyGoalTask]:
    query = db.query(FamilyGoalTask).filter(FamilyGoalTask.goal_id == goal_id)
    if not include_archived:
        query = query.filter(FamilyGoalTask.status == "active")
    return query.order_by(FamilyGoalTask.sort_order.asc(), FamilyGoalTask.id.asc()).all()


def get_task(db: Session, *, task_id: int) -> FamilyGoalTask:
    task = db.get(FamilyGoalTask, task_id)
    if task is None:
        raise FamilyGoalError("任务不存在", 404)
    return task


def update_task(
    db: Session,
    *,
    task_id: int,
    title: str | None = None,
    description: str | None = None,
    repeat_type: str | None = None,
    reward_amount: Decimal | None = None,
    status: str | None = None,
    sort_order: int | None = None,
) -> FamilyGoalTask:
    task = get_task(db, task_id=task_id)
    if title is not None:
        task.title = _require_text(title, "任务标题")[:160]
    if description is not None:
        task.description = description.strip() or None
    if repeat_type is not None:
        if repeat_type not in VALID_REPEAT_TYPES:
            raise FamilyGoalError("repeat_type 只能是 once 或 daily")
        task.repeat_type = repeat_type
    if reward_amount is not None:
        task.reward_amount = _validate_amount(reward_amount)
    if status is not None:
        if status not in ("active", "archived"):
            raise FamilyGoalError("任务状态不合法")
        task.status = status
    if sort_order is not None:
        task.sort_order = sort_order
    db.commit()
    db.refresh(task)
    return task


# ---------------- 任务实例 ----------------


def ensure_occurrences(
    db: Session,
    *,
    student_id: int,
    on_date: date,
    task_ids: list[int] | None = None,
) -> int:
    """为当天的每日任务补齐实例，返回新建条数。

    幂等由 UNIQUE(task_id, occurrence_date) 保证：并发下靠保存点吞掉冲突。
    惰性生成意味着孩子当天没打开知了就当成没有任务，不算漏做（有意取舍，省掉定时任务）。
    """
    query = (
        db.query(FamilyGoalTask)
        .join(FamilyGoal, FamilyGoal.id == FamilyGoalTask.goal_id)
        .filter(
            FamilyGoalTask.student_id == student_id,
            FamilyGoalTask.status == "active",
            FamilyGoal.status == "active",
        )
    )
    if task_ids is None:
        query = query.filter(FamilyGoalTask.repeat_type == "daily")
    else:
        query = query.filter(FamilyGoalTask.id.in_(task_ids))

    created = 0
    for task in query.all():
        exists = (
            db.query(FamilyTaskOccurrence.id)
            .filter(FamilyTaskOccurrence.task_id == task.id, FamilyTaskOccurrence.occurrence_date == on_date)
            .first()
        )
        if exists:
            continue
        try:
            with db.begin_nested():
                db.add(
                    FamilyTaskOccurrence(
                        task_id=task.id,
                        student_id=student_id,
                        occurrence_date=on_date,
                        status="pending",
                    )
                )
        except IntegrityError:
            continue
        created += 1
    db.commit()
    return created


def _occurrence_payload(
    occurrence: FamilyTaskOccurrence,
    task: FamilyGoalTask,
    goal: FamilyGoal,
    evidence: list[FamilyTaskEvidence],
) -> dict[str, Any]:
    return {
        "occurrence_id": occurrence.id,
        "task_id": task.id,
        "goal_id": goal.id,
        "student_id": occurrence.student_id,
        "title": task.title,
        "description": task.description,
        "goal_title": goal.title,
        "repeat_type": task.repeat_type,
        "status": occurrence.status,
        "occurrence_date": occurrence.occurrence_date.isoformat(),
        "reward_amount": _amount_str(resolve_reward_amount(task, goal)),
        "submit_note": occurrence.submit_note,
        "reject_reason": occurrence.reject_reason,
        "submitted_at": occurrence.submitted_at.isoformat() if occurrence.submitted_at else None,
        "reviewed_at": occurrence.reviewed_at.isoformat() if occurrence.reviewed_at else None,
        "evidence": [
            {"id": row.id, "url": build_public_url(row.content_ref), "sort_order": row.sort_order}
            for row in evidence
        ],
    }


def _load_occurrences(db: Session, occurrence_ids: list[int]) -> list[dict[str, Any]]:
    """按 id 批量取实例，带任务/目标/证据（一条 SQL 取主体，一条取证据）。"""
    if not occurrence_ids:
        return []
    rows = (
        db.query(FamilyTaskOccurrence, FamilyGoalTask, FamilyGoal)
        .join(FamilyGoalTask, FamilyGoalTask.id == FamilyTaskOccurrence.task_id)
        .join(FamilyGoal, FamilyGoal.id == FamilyGoalTask.goal_id)
        .filter(FamilyTaskOccurrence.id.in_(occurrence_ids))
        .all()
    )
    evidence_map: dict[int, list[FamilyTaskEvidence]] = {}
    for row in (
        db.query(FamilyTaskEvidence)
        .filter(FamilyTaskEvidence.occurrence_id.in_(occurrence_ids))
        .order_by(FamilyTaskEvidence.sort_order.asc(), FamilyTaskEvidence.id.asc())
        .all()
    ):
        evidence_map.setdefault(row.occurrence_id, []).append(row)
    return [
        _occurrence_payload(occurrence, task, goal, evidence_map.get(occurrence.id, []))
        for occurrence, task, goal in rows
    ]


def list_today_tasks(db: Session, *, student_id: int, on_date: date) -> list[dict[str, Any]]:
    """今天页要展示的任务：先补当天实例，再按创建顺序返回（含已提交/已确认的历史状态）。"""
    ensure_occurrences(db, student_id=student_id, on_date=on_date)
    ids = [
        row[0]
        for row in db.query(FamilyTaskOccurrence.id)
        .join(FamilyGoalTask, FamilyGoalTask.id == FamilyTaskOccurrence.task_id)
        .join(FamilyGoal, FamilyGoal.id == FamilyGoalTask.goal_id)
        .filter(
            FamilyTaskOccurrence.student_id == student_id,
            FamilyTaskOccurrence.occurrence_date == on_date,
            FamilyGoalTask.status == "active",
            FamilyGoal.status != "archived",
        )
        .order_by(FamilyGoalTask.sort_order.asc(), FamilyTaskOccurrence.id.asc())
        .all()
    ]
    return _load_occurrences(db, ids)


def get_occurrence_payload(db: Session, *, occurrence_id: int) -> dict[str, Any]:
    items = _load_occurrences(db, [occurrence_id])
    if not items:
        raise FamilyGoalError("提交不存在", 404)
    return items[0]


def list_pending_occurrences(
    db: Session, *, student_id: int, limit: int = FAMILY_PENDING_LIST_DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """待家长确认的提交，先交先看。"""
    ids = [
        row[0]
        for row in db.query(FamilyTaskOccurrence.id)
        .filter(
            FamilyTaskOccurrence.student_id == student_id,
            FamilyTaskOccurrence.status == "submitted",
        )
        .order_by(FamilyTaskOccurrence.submitted_at.asc(), FamilyTaskOccurrence.id.asc())
        .limit(limit)
        .all()
    ]
    return _load_occurrences(db, ids)


def submit_occurrence(
    db: Session,
    *,
    occurrence_id: int,
    student_id: int,
    note: str | None = None,
    evidence_refs: list[str] | None = None,
) -> FamilyTaskOccurrence:
    occurrence = db.get(FamilyTaskOccurrence, occurrence_id)
    if occurrence is None:
        raise FamilyGoalError("提交不存在", 404)
    if occurrence.student_id != student_id:
        raise FamilyGoalError("只能提交自己的任务", 403)
    if occurrence.status not in SUBMITTABLE_STATUSES:
        raise FamilyGoalError("该提交已处理，不能重复提交", 409)

    text = (note or "").strip()
    refs = [ref.strip() for ref in (evidence_refs or []) if isinstance(ref, str) and ref.strip()]
    if len(refs) > FAMILY_EVIDENCE_MAX_COUNT:
        raise FamilyGoalError(f"最多上传 {FAMILY_EVIDENCE_MAX_COUNT} 张图片")
    if not text and not refs:
        raise FamilyGoalError("请至少上传一张图片或写一句说明")

    # 重新提交以本次内容为准：覆盖说明并替换图片集合（驳回后重交不留旧图）
    db.query(FamilyTaskEvidence).filter(FamilyTaskEvidence.occurrence_id == occurrence.id).delete()
    for index, ref in enumerate(refs):
        db.add(
            FamilyTaskEvidence(
                occurrence_id=occurrence.id,
                content_ref=ref[:512],
                sort_order=index,
                uploaded_by=student_id,
            )
        )
    occurrence.submit_note = text or None
    occurrence.submitted_at = _now_utc()
    occurrence.reject_reason = None
    occurrence.status = "submitted"
    db.commit()
    db.refresh(occurrence)
    return occurrence


def review_occurrence(
    db: Session,
    *,
    occurrence_id: int,
    approve: bool,
    reason: str | None = None,
    reviewer_id: int | None = None,
) -> FamilyTaskOccurrence:
    """家长确认或驳回。只有 submitted 能审，重复审核返回 409（防重复发奖）。"""
    occurrence = db.get(FamilyTaskOccurrence, occurrence_id)
    if occurrence is None:
        raise FamilyGoalError("提交不存在", 404)
    if occurrence.status != "submitted":
        raise FamilyGoalError("该提交已处理", 409)

    now = _now_utc()
    if not approve:
        text = (reason or "").strip()
        if not text:
            raise FamilyGoalError("驳回需要填写理由")
        occurrence.status = "rejected"
        occurrence.reject_reason = text[:500]
        occurrence.reviewed_by = reviewer_id
        occurrence.reviewed_at = now
        db.commit()
        db.refresh(occurrence)
        return occurrence

    task = db.get(FamilyGoalTask, occurrence.task_id)
    goal = db.get(FamilyGoal, task.goal_id) if task else None
    amount = resolve_reward_amount(task, goal) if task and goal else None
    if amount is None:
        raise FamilyGoalError("任务没有奖励金额，无法确认")

    # 状态机校验放在 UPDATE 的 WHERE 里，并发/重复点都由影响行数兜住
    updated = (
        db.query(FamilyTaskOccurrence)
        .filter(FamilyTaskOccurrence.id == occurrence.id, FamilyTaskOccurrence.status == "submitted")
        .update(
            {
                "status": "approved",
                "reviewed_by": reviewer_id,
                "reviewed_at": now,
                "reward_amount_snapshot": amount,
                "reject_reason": None,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise FamilyGoalError("该提交已处理", 409)

    try:
        with db.begin_nested():
            db.add(
                FamilyRewardRecord(
                    student_id=occurrence.student_id,
                    occurrence_id=occurrence.id,
                    task_title=task.title,
                    goal_title=goal.title,
                    amount=amount,
                    confirmed_by=reviewer_id,
                    confirmed_at=now,
                )
            )
    except IntegrityError:
        db.rollback()
        raise FamilyGoalError("该提交已经记录过奖励", 409) from None

    db.commit()
    db.refresh(occurrence)
    return occurrence


def reward_summary(
    db: Session, *, student_id: int, limit: int = FAMILY_REWARD_RECORD_DEFAULT_LIMIT
) -> dict[str, Any]:
    """累计奖励只由已确认记录求和得出，不建余额字段。"""
    total = (
        db.query(func.coalesce(func.sum(FamilyRewardRecord.amount), 0))
        .filter(FamilyRewardRecord.student_id == student_id)
        .scalar()
    )
    records = (
        db.query(FamilyRewardRecord)
        .filter(FamilyRewardRecord.student_id == student_id)
        .order_by(FamilyRewardRecord.confirmed_at.desc(), FamilyRewardRecord.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "student_id": student_id,
        "total_amount": _amount_str(Decimal(total)) if total is not None else "0.00",
        "records": [
            {
                "id": record.id,
                "occurrence_id": record.occurrence_id,
                "task_title": record.task_title,
                "goal_title": record.goal_title,
                "amount": _amount_str(record.amount),
                "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
            }
            for record in records
        ],
    }


def resolve_bound_parent_id(db: Session, *, student_id: int) -> int | None:
    """内部集成入口没有登录用户，用绑定的唯一家长作为确认人；不唯一则留空。"""
    parents = access_service.list_bound_teachers(db, student_id)
    return parents[0].id if len(parents) == 1 else None


def has_bound_parent(db: Session, *, student_id: int) -> bool:
    """是否有家长审核账号绑定了该学生：没人绑就没人能确认作业、发奖励。"""
    return len(access_service.list_bound_teachers(db, student_id)) > 0


def goal_payload(goal: FamilyGoal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "student_id": goal.student_id,
        "title": goal.title,
        "description": goal.description,
        "reward_amount": _amount_str(goal.reward_amount),
        "creator_role": goal.creator_role,
        "status": goal.status,
        "start_date": goal.start_date,
        "end_date": goal.end_date,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
    }


def task_payload(task: FamilyGoalTask, goal: FamilyGoal) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal_id": task.goal_id,
        "student_id": task.student_id,
        "title": task.title,
        "description": task.description,
        "repeat_type": task.repeat_type,
        "reward_amount": _amount_str(task.reward_amount),
        "resolved_reward_amount": _amount_str(resolve_reward_amount(task, goal)),
        "status": task.status,
        "sort_order": task.sort_order,
    }
