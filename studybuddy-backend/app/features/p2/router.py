"""P2.1 路由：兴趣/反馈/推荐/属性面板。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .schemas import (
    AddInterestRequest,
    AttributeSnapshot,
    ConfirmPlanDraftRequest,
    CreateStudyPlanRequest,
    FeedbackItem,
    InitAttributesRequest,
    InterestItem,
    ProfileOnboardingRequest,
    ProfileSummary,
    RecommendationBoundaryItem,
    RecommendationItem,
    StudyPlan,
    StudyPlanItem,
    StudyPlanReminder,
    SubmitFeedbackRequest,
    UpdateInterestRequest,
    UpdateRecommendationBoundaryRequest,
    UpdateStudyPlanItemRequest,
    UpdateStudyPlanRequest,
)
from app.core.auth import access_service
from . import attribute, feedback, interests, profile, recommendation, study_plan

router = APIRouter(prefix="/api", tags=["p2"])


def _student_id(db: Session, user: User, student_id: int | None) -> int:
    """parent 可查指定学生；student 只能查自己。"""
    return resolve_accessible_student_id(db, user, student_id)


# ---- 兴趣 ----


@router.get("/students/{student_id}/interests", response_model=list[InterestItem])
def api_list_interests(student_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[InterestItem]:
    sid = _student_id(db, user, student_id)
    return interests.list_interests(db, sid)


@router.post("/students/{student_id}/interests", response_model=InterestItem)
def api_add_interest(
    student_id: int,
    req: AddInterestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterestItem:
    sid = resolve_accessible_student_id(db, user, student_id)
    source = "manual" if user.role == "student" else "inferred"
    try:
        return interests.add_interest(db, sid, req.tag, source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/interests/{interest_id}", response_model=InterestItem)
def api_confirm_interest(
    interest_id: int,
    req: UpdateInterestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterestItem:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生能确认兴趣")
    if not req.approved:
        raise HTTPException(status_code=422, detail="确认接口只支持 approved=true；移除请使用 DELETE")
    item = interests.confirm_interest(db, interest_id, user.id)
    if not item:
        raise HTTPException(status_code=404, detail="兴趣不存在")
    return item


@router.delete("/interests/{interest_id}", status_code=204)
def api_remove_interest(
    interest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生能移除兴趣")
    ok = interests.remove_interest(db, interest_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="兴趣不存在")


# ---- 学习计划 ----


@router.get("/students/{student_id}/study-plans", response_model=list[StudyPlan])
def api_list_study_plans(
    student_id: int,
    status: str | None = Query("active", description="active/completed/archived；传空值查全部"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StudyPlan]:
    sid = _student_id(db, user, student_id)
    student = db.get(User, sid)
    student_mode = getattr(student, "mode", "study") if student else "study"
    return study_plan.list_study_plans(db, sid, status=status, mode=student_mode)


@router.post("/students/{student_id}/study-plans", response_model=StudyPlan)
def api_create_study_plan(
    student_id: int,
    req: CreateStudyPlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyPlan:
    sid = _student_id(db, user, student_id)
    try:
        student = db.get(User, sid)
        student_mode = getattr(student, "mode", "study") if student else "study"
        return study_plan.create_study_plan(db, sid, req.title, req.items, req.focus, req.planned_date, created_by=user.id, description=req.description, context_refs=req.context_refs, mode=student_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/study-plan-drafts/{draft_id}/confirm")
def api_confirm_plan_draft(
    draft_id: int,
    req: ConfirmPlanDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """学生点卡片'确认并创建'后调用：用草案 draft_data 原子创建正式计划。"""
    from app.features.agent import study_plan_flow

    sid = resolve_accessible_student_id(db, user, req.student_id)
    result = study_plan_flow.confirm_and_create(db, draft_id, req.revision, sid, user.id)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return {"plan_id": result.plan_id}


@router.get("/study-plan-drafts/{draft_id}")
def api_get_plan_draft(
    draft_id: int,
    student_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查草案当前状态：前端刷新后判断是否还需展示确认卡（已 created 的不恢复）。"""
    from app.features.agent import study_plan_flow

    sid = resolve_accessible_student_id(db, user, student_id)
    draft = study_plan_flow.get_draft(db, draft_id, sid)
    if not draft:
        raise HTTPException(status_code=404, detail="草案不存在或无权访问")
    data = draft.draft_data or {}
    return {
        "id": draft.id,
        "status": draft.status,
        "created_plan_id": draft.created_plan_id,
        "revision": draft.revision,
        # M1：归属与过期由服务端给出，前端不猜时区/不查库
        "chat_session_id": draft.chat_session_id,
        "created_at": draft.created_at.isoformat() + "Z" if draft.created_at else None,
        "is_expired": study_plan_flow.draft_is_expired(draft),
        "title": data.get("title", ""),
        "focus": data.get("focus"),
        "planned_date": data.get("planned_date"),
        "items": data.get("items", []),
        "expires_at": draft.expires_at.isoformat() if draft.expires_at else None,
    }


@router.post("/study-plans/{plan_id}/archive", response_model=StudyPlan)
def api_archive_study_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyPlan:
    plan = study_plan.get_study_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    resolve_accessible_student_id(db, user, plan.student_id)
    archived = study_plan.archive_study_plan(db, plan_id)
    if not archived:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return archived


@router.post("/study-plans/{plan_id}/carry-over", response_model=StudyPlan)
def api_carry_over_study_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyPlan:
    source = study_plan.get_study_plan(db, plan_id)
    if not source:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    sid = resolve_accessible_student_id(db, user, source.student_id)
    try:
        return study_plan.carry_over_study_plan(db, student_id=sid, source_plan_id=plan_id, created_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/study-plans/{plan_id}", response_model=StudyPlan)
def api_update_study_plan(
    plan_id: int,
    req: UpdateStudyPlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyPlan:
    plan = study_plan.get_study_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    resolve_accessible_student_id(db, user, plan.student_id)
    try:
        updated = study_plan.update_study_plan(
            db, plan_id, title=req.title, description=req.description, planned_date=req.planned_date, revision=req.revision
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return updated


@router.patch("/study-plan-items/{item_id}", response_model=StudyPlanItem)
def api_update_study_plan_item(
    item_id: int,
    req: UpdateStudyPlanItemRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyPlanItem:
    plan = study_plan.get_study_plan_by_item(db, item_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划项不存在")
    resolve_accessible_student_id(db, user, plan.student_id)
    try:
        if req.status == "done":
            # done 必须带学生作答证据：委托共享 service 收口 Attempt/状态/反馈/plan 刷新，
            # 与 Agent 工具共用同一实现，空白证据由 service 校验拒绝（422）。
            item = study_plan.record_study_plan_item_assessment(
                db,
                student_id=plan.student_id,
                item_id=item_id,
                assessment="passed",
                evidence_summary=req.evidence_summary,
            )
        else:
            item = study_plan.update_study_plan_item_status(db, item_id, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="计划项不存在")
    return item


@router.get("/study-plan-reminders/due", response_model=list[StudyPlanReminder])
def api_list_due_study_plan_reminders(
    student_id: int | None = Query(default=None, description="家长可指定绑定学生；不传则返回全部绑定学生"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StudyPlanReminder]:
    if user.role == "student":
        sid = _student_id(db, user, student_id)
        student = db.get(User, sid)
        student_mode = getattr(student, "mode", "study") if student else "study"
        return study_plan.list_due_study_plan_reminders(db, [sid], limit=limit, mode=student_mode)
    if student_id is not None:
        sid = _student_id(db, user, student_id)
        student = db.get(User, sid)
        student_mode = getattr(student, "mode", "study") if student else "study"
        return study_plan.list_due_study_plan_reminders(db, [sid], limit=limit, mode=student_mode)
    students = access_service.list_accessible_students(db, user.id)
    student_mode = getattr(students[0], "mode", "study") if students else "study"
    # 家长批量视角：不过滤 mode（多学生可能模式不同，混合提醒都展示）
    return study_plan.list_due_study_plan_reminders(db, [student.id for student in students], limit=limit, mode=None)


# ---- 反馈 ----


@router.get("/students/{student_id}/feedback", response_model=list[FeedbackItem])
def api_list_feedback(student_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[FeedbackItem]:
    sid = _student_id(db, user, student_id)
    return feedback.list_feedback(db, sid)


@router.post("/students/{student_id}/feedback", response_model=FeedbackItem)
def api_submit_feedback(
    student_id: int,
    req: SubmitFeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FeedbackItem:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生能提交反馈")
    resolve_accessible_student_id(db, user, student_id)
    try:
        return feedback.submit_feedback(db, user.id, req.feedback_type, req.content, req.related_resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- 推荐 ----


@router.get("/students/{student_id}/recommendation-boundary", response_model=RecommendationBoundaryItem)
def api_get_recommendation_boundary(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationBoundaryItem:
    sid = _student_id(db, user, student_id)
    return recommendation.get_recommendation_boundary(db, sid)


@router.put("/students/{student_id}/recommendation-boundary", response_model=RecommendationBoundaryItem)
def api_update_recommendation_boundary(
    student_id: int,
    req: UpdateRecommendationBoundaryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecommendationBoundaryItem:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="只有家长能设置推荐边界")
    sid = _student_id(db, user, student_id)
    return recommendation.update_recommendation_boundary(
        db,
        sid,
        req.allowed_platforms,
        req.blocked_keywords,
        req.daily_limit,
        req.allow_entertainment_interests,
        updated_by=user.id,
    )


@router.get("/students/{student_id}/recommendations", response_model=list[RecommendationItem])
def api_list_recommendations(student_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[RecommendationItem]:
    sid = _student_id(db, user, student_id)
    return recommendation.list_recommendations(db, sid)


@router.post("/recommendations/{rec_id}/click")
def api_mark_clicked(rec_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    student_ids = [user.id] if user.role == "student" else [student.id for student in access_service.list_accessible_students(db, user.id)]
    ok = recommendation.mark_clicked(db, rec_id, student_ids)
    if not ok:
        raise HTTPException(status_code=404, detail="推荐不存在")
    return {"clicked": True}


# ---- 属性面板 ----


@router.get("/students/{student_id}/profile/summary", response_model=ProfileSummary)
def api_get_profile_summary(
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileSummary:
    sid = _student_id(db, user, student_id)
    return profile.get_profile_summary(db, sid)


@router.post("/students/{student_id}/profile/onboarding", response_model=ProfileSummary)
def api_save_profile_onboarding(
    student_id: int,
    req: ProfileOnboardingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileSummary:
    sid = _student_id(db, user, student_id)
    return profile.save_profile_onboarding(db, sid, req, actor_role=user.role)


@router.get("/students/{student_id}/attributes")
def api_get_attributes(
    student_id: int,
    history: bool = Query(False, description="是否返回历史成长曲线"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    sid = _student_id(db, user, student_id)
    if history:
        return {"history": [s.model_dump() for s in attribute.get_attribute_history(db, sid)]}
    latest = attribute.get_latest_attributes(db, sid)
    return {"current": latest.model_dump() if latest else None}


@router.post("/students/{student_id}/attributes/init", response_model=AttributeSnapshot)
def api_init_attributes(
    student_id: int,
    req: InitAttributesRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttributeSnapshot:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="只有家长能初始化属性")
    sid = resolve_accessible_student_id(db, user, student_id)
    return attribute.init_attributes(db, sid, req.exam_scores)
