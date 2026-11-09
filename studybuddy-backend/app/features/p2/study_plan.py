from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from .schemas import (
    StudyPlan as StudyPlanSchema,
    StudyPlanItem as StudyPlanItemSchema,
    StudyPlanItemInput,
    StudyPlanReminder,
)

STALE_ACTIVE_PLAN_DAYS = 14


def _format_dt(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _format_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _plan_overdue_days(plan: StudyPlan) -> int:
    if plan.status != "active" or not plan.planned_date:
        return 0
    return max((date.today() - plan.planned_date).days, 0)


def _archive_stale_active_plans(db: Session, student_ids: list[int] | None = None) -> None:
    stale_before = date.today() - timedelta(days=STALE_ACTIVE_PLAN_DAYS)
    query = db.query(StudyPlan).filter(StudyPlan.status == "active", StudyPlan.planned_date < stale_before)
    if student_ids is not None:
        if not student_ids:
            return
        query = query.filter(StudyPlan.student_id.in_(student_ids))
    stale_plans = query.all()
    if not stale_plans:
        return
    for plan in stale_plans:
        plan.status = "archived"
    db.commit()


def _to_plan_item(item: StudyPlanItem) -> StudyPlanItemSchema:
    return StudyPlanItemSchema(
        id=item.id,
        title=item.title,
        target=item.target,
        minutes=item.minutes,
        status=item.status,
        related_tags=item.related_tags or [],
        sort_order=item.sort_order,
        completed_at=_format_dt(item.completed_at),
    )


def _build_plan_reminder_message(plan: StudyPlan, items: list[StudyPlanItem], overdue_days: int) -> str | None:
    todo_items = [item for item in items if item.status in ("todo", "in_progress")]
    if not todo_items:
        return None
    first_item = todo_items[0]
    if overdue_days > 0:
        return f"计划「{plan.title}」已逾期 {overdue_days} 天，建议今天先补「{first_item.title}」。"
    if plan.planned_date == date.today():
        return f"今天计划「{plan.title}」还有 {len(todo_items)} 个任务，建议先做「{first_item.title}」。"
    return None


def _to_plan(db: Session, plan: StudyPlan) -> StudyPlanSchema:
    items = db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == plan.id).order_by(StudyPlanItem.sort_order, StudyPlanItem.id).all()
    overdue_days = _plan_overdue_days(plan)
    return StudyPlanSchema(
        id=plan.id,
        student_id=plan.student_id,
        mode=plan.mode,
        title=plan.title,
        focus=plan.focus,
        description=plan.description,
        context_refs=plan.context_refs,
        source_plan_id=plan.source_plan_id,
        revision=plan.revision,
        status=plan.status,
        planned_date=_format_date(plan.planned_date),
        is_overdue=overdue_days > 0,
        overdue_days=overdue_days,
        reminder_message=_build_plan_reminder_message(plan, items, overdue_days),
        created_by=plan.created_by,
        created_at=_format_dt(plan.created_at) or "",
        items=[_to_plan_item(item) for item in items],
    )


def _parse_plan_date(value: str | None) -> date | None:
    if not value:
        return date.today()
    return date.fromisoformat(value)


def _create_plan_records(
    db: Session,
    student_id: int,
    title: str,
    items: list[StudyPlanItemInput],
    focus: str | None = None,
    planned_date: str | None = None,
    created_by: int | None = None,
    description: str | None = None,
    context_refs: dict | None = None,
    mode: str = "study",
) -> StudyPlan:
    """建 plan + items 记录，只 flush 不 commit。调用方负责 commit。

    抽出供 create_study_plan（直接创建）和 study_plan_flow.confirm_and_create
    （草案确认后原子创建）共用，确保两条路径落库逻辑一致。
    """
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("学习计划名称不能为空")
    clean_items = [item for item in items if item.title.strip()]
    if not clean_items:
        raise ValueError("学习计划至少需要 1 个任务")
    plan = StudyPlan(
        student_id=student_id,
        title=clean_title[:128],
        focus=(focus.strip()[:256] if focus else None),
        description=(description.strip() if description else None),
        context_refs=context_refs,
        planned_date=_parse_plan_date(planned_date),
        created_by=created_by,
        mode=mode,
    )
    db.add(plan)
    db.flush()  # 拿 plan.id，不单独 commit；由调用方决定何时提交

    for index, item in enumerate(clean_items, start=1):
        minutes = max(5, min(60, int(item.minutes or 20)))
        db.add(
            StudyPlanItem(
                plan_id=plan.id,
                title=item.title.strip()[:160],
                target=item.target.strip() if item.target else None,
                minutes=minutes,
                related_tags=item.related_tags,
                sort_order=index,
            )
        )
    return plan


def create_study_plan(
    db: Session,
    student_id: int,
    title: str,
    items: list[StudyPlanItemInput],
    focus: str | None = None,
    planned_date: str | None = None,
    created_by: int | None = None,
    description: str | None = None,
    context_refs: dict | None = None,
    mode: str = "study",
) -> StudyPlanSchema:
    """创建一份学习计划，并把任务拆成可完成的计划项。单事务：plan + items 一起提交，避免空计划。"""
    plan = _create_plan_records(
        db, student_id, title, items, focus, planned_date, created_by, description, context_refs, mode=mode
    )
    db.commit()
    db.refresh(plan)
    return _to_plan(db, plan)


def list_study_plans(db: Session, student_id: int, status: str | None = "active", limit: int = 20, mode: str = "study") -> list[StudyPlanSchema]:
    _archive_stale_active_plans(db, [student_id])
    query = db.query(StudyPlan).filter(StudyPlan.student_id == student_id, StudyPlan.mode == mode)
    if status:
        query = query.filter(StudyPlan.status == status)
    plans = query.order_by(StudyPlan.id.desc()).limit(limit).all()
    return [_to_plan(db, plan) for plan in plans]


def get_study_plan(db: Session, plan_id: int) -> StudyPlan | None:
    return db.get(StudyPlan, plan_id)


def carry_over_study_plan(
    db: Session,
    *,
    student_id: int,
    source_plan_id: int,
    created_by: int | None,
    planned_date: date | None = None,
) -> StudyPlanSchema:
    """复制旧计划未完成任务到今天，并在同一事务内归档来源计划。

    source_plan_id 的唯一约束保证重复点击/重试只产生一份新计划；已复制时直接返回原结果。
    """
    source = db.query(StudyPlan).filter(
        StudyPlan.id == source_plan_id,
        StudyPlan.student_id == student_id,
    ).with_for_update().first()
    if not source:
        raise PermissionError("无权沿用该学习计划")

    existing = db.query(StudyPlan).filter(StudyPlan.source_plan_id == source.id).first()
    if existing:
        return _to_plan(db, existing)

    today = planned_date or date.today()
    if source.planned_date == today:
        raise ValueError("今天计划不需要沿用")

    source_items = db.query(StudyPlanItem).filter(
        StudyPlanItem.plan_id == source.id,
        StudyPlanItem.status.in_(("todo", "in_progress")),
    ).order_by(StudyPlanItem.sort_order, StudyPlanItem.id).all()
    if not source_items:
        raise ValueError("旧计划没有可沿用的未完成任务")

    refs = dict(source.context_refs or {})
    refs["carried_from_plan_id"] = source.id
    plan = _create_plan_records(
        db,
        student_id,
        f"继续：{source.title}",
        [
            StudyPlanItemInput(
                title=item.title,
                target=item.target,
                minutes=item.minutes,
                related_tags=item.related_tags or [],
            )
            for item in source_items
        ],
        focus=source.focus,
        planned_date=today.isoformat(),
        created_by=created_by,
        description=source.description,
        context_refs=refs,
        mode=source.mode,
    )
    plan.source_plan_id = source.id
    source.status = "archived"
    db.commit()
    db.refresh(plan)
    return _to_plan(db, plan)


def update_study_plan(
    db: Session,
    plan_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    planned_date: str | None = None,
    revision: int,
) -> StudyPlanSchema | None:
    """修改计划标题/描述/日期，乐观锁 revision 校验（不匹配拒绝）。单事务。

    只改传入的非 None 字段；revision 必填，校验通过后 +1。
    """
    plan = db.get(StudyPlan, plan_id)
    if not plan:
        return None
    if plan.revision != revision:
        raise ValueError(f"计划已被修改（当前 revision={plan.revision}），请刷新后重试")
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ValueError("学习计划名称不能为空")
        plan.title = clean[:128]
    if description is not None:
        plan.description = description.strip() or None
    if planned_date is not None:
        plan.planned_date = _parse_plan_date(planned_date)
    plan.revision = plan.revision + 1
    db.commit()
    db.refresh(plan)
    return _to_plan(db, plan)


def archive_study_plan(db: Session, plan_id: int) -> StudyPlanSchema | None:
    plan = get_study_plan(db, plan_id)
    if not plan:
        return None
    plan.status = "archived"
    db.commit()
    db.refresh(plan)
    return _to_plan(db, plan)


def list_due_study_plan_reminders(
    db: Session,
    student_ids: list[int] | None = None,
    limit: int = 50,
    archive_stale: bool = True,
    mode: str = "study",
) -> list[StudyPlanReminder]:
    if archive_stale:
        _archive_stale_active_plans(db, student_ids)
    query = db.query(StudyPlan).filter(StudyPlan.status == "active")
    if mode is not None:
        query = query.filter(StudyPlan.mode == mode)
    if not archive_stale:
        stale_before = date.today() - timedelta(days=STALE_ACTIVE_PLAN_DAYS)
        query = query.filter(StudyPlan.planned_date >= stale_before)
    if student_ids is not None:
        if not student_ids:
            return []
        query = query.filter(StudyPlan.student_id.in_(student_ids))
    plans = query.order_by(StudyPlan.planned_date.is_(None), StudyPlan.planned_date.asc(), StudyPlan.id.desc()).limit(limit).all()
    reminders: list[StudyPlanReminder] = []
    for plan in plans:
        items = db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == plan.id).order_by(StudyPlanItem.sort_order, StudyPlanItem.id).all()
        todo_items = [item for item in items if item.status in ("todo", "in_progress")]
        if not todo_items:
            continue
        overdue_days = _plan_overdue_days(plan)
        message = _build_plan_reminder_message(plan, items, overdue_days)
        if not message:
            continue
        reminders.append(
            StudyPlanReminder(
                plan_id=plan.id,
                student_id=plan.student_id,
                title=plan.title,
                planned_date=_format_date(plan.planned_date),
                is_overdue=overdue_days > 0,
                overdue_days=overdue_days,
                todo_count=len(todo_items),
                todo_minutes=sum(item.minutes for item in todo_items),
                first_todo_title=todo_items[0].title,
                first_todo_item_id=todo_items[0].id,
                reminder_message=message,
            )
        )
    return reminders


def _build_plan_item_feedback(item: StudyPlanItem, status: str) -> tuple[str, str] | None:
    if status == "done":
        content = f"完成学习计划任务「{item.title}」，预计用时 {item.minutes} 分钟。"
        if item.target:
            content += f"目标：{item.target}"
        return "duration", content
    if status == "skipped":
        content = f"跳过学习计划任务「{item.title}」，需要下次复盘原因。"
        if item.target:
            content += f"原目标：{item.target}"
        return "difficulty", content
    return None


def update_study_plan_item_status(db: Session, item_id: int, status: str) -> StudyPlanItemSchema | None:
    if status not in {"todo", "done", "skipped"}:
        raise ValueError("计划项状态必须是 todo/done/skipped")
    item = db.get(StudyPlanItem, item_id)
    if not item:
        return None
    previous_status = item.status
    item.status = status
    # naive UTC，与 aggregate_daily_facts 的 utc_start/utc_end 窗口口径一致；
    # 若用 datetime.now() 写入本地墙上时间，本地 8 点后完成的任务会落不进当日窗口，
    # 导致每日摘要 evidence 为空。对齐 generated_at/checked_in_at 的 naive UTC 口径。
    # microsecond=0：DATETIME 列秒级精度会对微秒四舍五入，.5+ 进位到下一秒可能 >
    # utc_end(微秒精度)被排除出当日窗口；写秒级杜绝该边界 flake。
    item.completed_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) if status == "done" else None
    feedback = _build_plan_item_feedback(item, status) if previous_status != status else None
    if feedback:
        # 计划项完成时自动记一条学习反馈：content 由 _build_plan_item_feedback 生成，
        # 与手动 submit_feedback 的 content 格式不同，故直接 new LearningFeedback 而非
        # 调 feedback 子模块（模型级共享，非函数级依赖）。
        feedback_type, content = feedback
        plan = db.get(StudyPlan, item.plan_id)
        if plan:
            db.add(LearningFeedback(student_id=plan.student_id, feedback_type=feedback_type, content=content))
    db.commit()
    db.refresh(item)
    _refresh_plan_status(db, item.plan_id)
    return _to_plan_item(item)


def get_study_plan_by_item(db: Session, item_id: int) -> StudyPlan | None:
    item = db.get(StudyPlanItem, item_id)
    return db.get(StudyPlan, item.plan_id) if item else None


def record_study_plan_item_assessment(
    db: Session,
    *,
    student_id: int,
    item_id: int,
    assessment: str,
    evidence_summary: str | None = None,
    reason: str | None = None,
    confidence: float | None = None,
    taught_scope: str | None = None,
    next_start: str | None = None,
) -> StudyPlanItemSchema:
    """记录计划项完成判定（HTTP 与 Agent 工具共用的唯一事务入口）。

    一个事务内完成：越权校验 -> 证据校验 -> 写 StudyPlanItemAttempt -> 状态映射
    （passed->done / needs_retry->todo / blocked->in_progress）-> completed_at ->
    LearningFeedback -> _refresh_plan_status。

    - passed 必须带非空证据（strip 后判空），否则 ValueError 且状态不变
    - 已 done 且有 passed Attempt 时幂等返回，不重复写 Attempt/反馈/完成时间
    - 越权抛 PermissionError（fail-closed）
    """
    from app.models.p2 import StudyPlanItemAttempt

    if assessment not in ("passed", "needs_retry", "blocked"):
        raise ValueError("assessment 必须是 passed/needs_retry/blocked")
    item = db.get(StudyPlanItem, item_id)
    if not item:
        raise ValueError("计划项不存在")
    plan = db.get(StudyPlan, item.plan_id)
    if not plan or plan.student_id != student_id:
        raise PermissionError("无权操作该计划项")
    if assessment == "passed":
        evidence = (evidence_summary or "").strip()
        if not evidence:
            raise ValueError("完成判定需要学生作答证据（evidence_summary），请先让学生复述/回答后再评估为 passed")
    if assessment == "blocked":
        if not (reason and reason.strip()):
            raise ValueError("blocked 需要卡点原因 reason")
        has_evidence = bool(evidence_summary and evidence_summary.strip())
        has_scope = bool(taught_scope and taught_scope.strip())
        if not has_evidence and not has_scope:
            raise ValueError("blocked 需要作答证据或讲解范围（taught_scope）")
    # 幂等：已 done 直接返回（含历史 done 无 Attempt 的存量脏数据），
    # 不补证、不重置 completed_at（补证会把旧完成时间挪到今天，daily record 幽灵记录）
    if assessment == "passed" and item.status == "done":
        return _to_plan_item(item)
    attempt = StudyPlanItemAttempt(
        plan_item_id=item.id,
        student_id=student_id,
        assessment=assessment,
        evidence_summary=evidence_summary.strip() if evidence_summary else None,
        reason=reason.strip() if reason else None,
        confidence=confidence,
        taught_scope=taught_scope.strip() if taught_scope else None,
        next_start=next_start.strip() if next_start else None,
    )
    db.add(attempt)
    previous_status = item.status
    if assessment == "passed":
        item.status = "done"
        item.completed_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    elif assessment == "needs_retry":
        item.status = "todo"
        item.completed_at = None  # 退回重做，清完成时间（与 update_study_plan_item_status 口径一致）
    else:  # blocked
        item.status = "in_progress"
        item.completed_at = None
    feedback = _build_plan_item_feedback(item, item.status) if previous_status != item.status and assessment == "passed" else None
    if feedback:
        feedback_type, content = feedback
        db.add(LearningFeedback(student_id=plan.student_id, feedback_type=feedback_type, content=content))
    db.commit()
    db.refresh(item)
    _refresh_plan_status(db, item.plan_id)
    return _to_plan_item(item)


def _refresh_plan_status(db: Session, plan_id: int) -> None:
    plan = db.get(StudyPlan, plan_id)
    if not plan:
        return
    items = db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == plan_id).all()
    if items and all(item.status in {"done", "skipped"} for item in items):
        plan.status = "completed"
    elif plan.status == "completed":
        plan.status = "active"
    db.commit()
