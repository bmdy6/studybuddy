"""家庭目标与任务激励路由（浏览器入口，JWT）。

权限：student_id 一律经 resolve_accessible_student_id 重解析（学生只能是自己，家长必须是
绑定孩子）；对象级接口（目标/任务/提交）再按其归属学生复核一次，不信任前端传的 id。

内部集成入口见 router_integration.py（X-Internal-Token），两者共用同一套 service。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.constants import ALLOWED_FAMILY_EVIDENCE_EXTENSIONS, FAMILY_PENDING_LIST_DEFAULT_LIMIT
from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from app.utils.cos import build_public_url, upload_file

from . import service
from .schemas import (
    CreateGoalRequest,
    CreateTaskRequest,
    EvidenceUploadResponse,
    FamilyGoalContext,
    GoalItem,
    ReviewOccurrenceRequest,
    RewardSummary,
    SubmitOccurrenceRequest,
    TaskItem,
    TodayTaskItem,
    UpdateGoalRequest,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/api", tags=["family-goal"])

T = TypeVar("T")


def call_or_http(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """把 service 的业务错误转成 HTTP 响应，避免每个端点重复 try/except。"""
    try:
        return fn(*args, **kwargs)
    except service.FamilyGoalError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message) from None


def _task_item(db: Session, task_id: int) -> TaskItem:
    task = call_or_http(service.get_task, db, task_id=task_id)
    goal = call_or_http(service.get_goal, db, goal_id=task.goal_id)
    return TaskItem(**service.task_payload(task, goal))


@router.post("/students/{student_id}/family-goals", response_model=GoalItem, status_code=201)
def api_create_goal(
    student_id: int,
    payload: CreateGoalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalItem:
    sid = resolve_accessible_student_id(db, user, student_id)
    goal = call_or_http(
        service.create_goal,
        db,
        student_id=sid,
        created_by=user.id,
        creator_role=service.creator_role_of(user),
        title=payload.title,
        description=payload.description,
        reward_amount=service.parse_amount(payload.reward_amount),
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return GoalItem(**service.goal_payload(goal))


@router.get("/students/{student_id}/family-goals", response_model=list[GoalItem])
def api_list_goals(
    student_id: int,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GoalItem]:
    sid = resolve_accessible_student_id(db, user, student_id)
    goals = service.list_goals(db, student_id=sid, include_archived=include_archived)
    return [GoalItem(**service.goal_payload(goal)) for goal in goals]


@router.patch("/family-goals/{goal_id}", response_model=GoalItem)
def api_update_goal(
    goal_id: int,
    payload: UpdateGoalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalItem:
    goal = call_or_http(service.get_goal, db, goal_id=goal_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=goal.student_id)
    updated = call_or_http(
        service.update_goal,
        db,
        goal_id=goal_id,
        title=payload.title,
        description=payload.description,
        reward_amount=service.parse_amount(payload.reward_amount),
        status=payload.status,
    )
    return GoalItem(**service.goal_payload(updated))


@router.post("/family-goals/{goal_id}/tasks", response_model=TaskItem, status_code=201)
def api_create_task(
    goal_id: int,
    payload: CreateTaskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskItem:
    goal = call_or_http(service.get_goal, db, goal_id=goal_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=goal.student_id)
    task = call_or_http(
        service.create_task,
        db,
        goal_id=goal_id,
        student_id=goal.student_id,
        created_by=user.id,
        title=payload.title,
        description=payload.description,
        repeat_type=payload.repeat_type,
        reward_amount=service.parse_amount(payload.reward_amount),
        sort_order=payload.sort_order,
    )
    return TaskItem(**service.task_payload(task, goal))


@router.get("/family-goals/{goal_id}/tasks", response_model=list[TaskItem])
def api_list_tasks(
    goal_id: int,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskItem]:
    goal = call_or_http(service.get_goal, db, goal_id=goal_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=goal.student_id)
    tasks = service.list_tasks(db, goal_id=goal_id, include_archived=include_archived)
    return [TaskItem(**service.task_payload(task, goal)) for task in tasks]


@router.patch("/family-goal-tasks/{task_id}", response_model=TaskItem)
def api_update_task(
    task_id: int,
    payload: UpdateTaskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskItem:
    task = call_or_http(service.get_task, db, task_id=task_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=task.student_id)
    call_or_http(
        service.update_task,
        db,
        task_id=task_id,
        title=payload.title,
        description=payload.description,
        repeat_type=payload.repeat_type,
        reward_amount=service.parse_amount(payload.reward_amount),
        status=payload.status,
        sort_order=payload.sort_order,
    )
    return _task_item(db, task_id)


@router.get("/students/{student_id}/today-family-tasks", response_model=list[TodayTaskItem])
def api_today_tasks(
    student_id: int,
    on_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TodayTaskItem]:
    sid = resolve_accessible_student_id(db, user, student_id)
    target_date = on_date or service.today_in_app_timezone()
    items = service.list_today_tasks(db, student_id=sid, on_date=target_date)
    return [TodayTaskItem(**item) for item in items]


@router.post("/family-task-occurrences/{occurrence_id}/submit", response_model=TodayTaskItem)
def api_submit_occurrence(
    occurrence_id: int,
    payload: SubmitOccurrenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TodayTaskItem:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="完成提交由学生本人操作")
    current = call_or_http(service.get_occurrence_payload, db, occurrence_id=occurrence_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=current["student_id"])
    call_or_http(
        service.submit_occurrence,
        db,
        occurrence_id=occurrence_id,
        student_id=user.id,
        note=payload.note,
        evidence_refs=payload.evidence_refs,
    )
    return TodayTaskItem(**service.get_occurrence_payload(db, occurrence_id=occurrence_id))


@router.get("/students/{student_id}/family-goal-context", response_model=FamilyGoalContext)
def api_family_goal_context(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FamilyGoalContext:
    """只读上下文：学生自查或家长查绑定孩子是否已有家长审核账号（UI 提示用）。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    return FamilyGoalContext(parent_bound=service.has_bound_parent(db, student_id=sid))


@router.get("/students/{student_id}/family-rewards", response_model=RewardSummary)
def api_reward_summary(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RewardSummary:
    sid = resolve_accessible_student_id(db, user, student_id)
    return RewardSummary(**service.reward_summary(db, student_id=sid))


@router.get("/students/{student_id}/family-task-reviews", response_model=list[TodayTaskItem])
def api_list_reviews(
    student_id: int,
    status: str = Query(default="submitted"),
    limit: int = Query(default=FAMILY_PENDING_LIST_DEFAULT_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TodayTaskItem]:
    """家长待审列表（个人工作台卡片用；学生端也能看自己的提交）。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    if status != "submitted":
        raise HTTPException(status_code=422, detail="当前只支持查询待确认的提交")
    items = service.list_pending_occurrences(db, student_id=sid, limit=limit)
    return [TodayTaskItem(**item) for item in items]


def _load_occurrence_for_review(
    db: Session, user: User, occurrence_id: int
) -> dict[str, Any]:
    """审核人必须是家长，且审核对象属于其绑定的学生。

    学生本人不能审自己的提交——否则等于自己给自己发奖励（奖励失去意义）。
    """
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="确认完成由家长操作")
    current = call_or_http(service.get_occurrence_payload, db, occurrence_id=occurrence_id)
    call_or_http(service.assert_can_access_student, db, user=user, student_id=current["student_id"])
    return current


@router.post("/family-task-occurrences/{occurrence_id}/approve", response_model=TodayTaskItem)
def api_approve_occurrence(
    occurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TodayTaskItem:
    """家长确认完成：确认人与登录用户一致，不靠前端传。"""
    _load_occurrence_for_review(db, user, occurrence_id)
    call_or_http(
        service.review_occurrence,
        db,
        occurrence_id=occurrence_id,
        approve=True,
        reviewer_id=user.id,
    )
    return TodayTaskItem(**service.get_occurrence_payload(db, occurrence_id=occurrence_id))


@router.post("/family-task-occurrences/{occurrence_id}/reject", response_model=TodayTaskItem)
def api_reject_occurrence(
    occurrence_id: int,
    payload: ReviewOccurrenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TodayTaskItem:
    _load_occurrence_for_review(db, user, occurrence_id)
    call_or_http(
        service.review_occurrence,
        db,
        occurrence_id=occurrence_id,
        approve=False,
        reason=payload.reason,
        reviewer_id=user.id,
    )
    return TodayTaskItem(**service.get_occurrence_payload(db, occurrence_id=occurrence_id))


@router.post("/family-task-evidence/upload", response_model=EvidenceUploadResponse, status_code=201)
async def api_upload_evidence(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> EvidenceUploadResponse:
    filename = file.filename or "evidence"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_FAMILY_EVIDENCE_EXTENSIONS:
        allowed = "、".join(sorted(ALLOWED_FAMILY_EVIDENCE_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"完成证据只支持图片：{allowed}")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="上传文件为空")
    try:
        content_ref = await asyncio.to_thread(upload_file, file_bytes, ext, "family_goal")
    except RuntimeError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    return EvidenceUploadResponse(content_ref=content_ref, url=build_public_url(content_ref))
