"""Authenticated server-to-server family-task integration routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.constants import FAMILY_PENDING_LIST_DEFAULT_LIMIT
from app.database import get_db
from app.deps import require_internal_token

from . import service
from .router import call_or_http
from .schemas import ReviewOccurrenceRequest, RewardSummary, TodayTaskItem

router = APIRouter(
    prefix="/api/integration/family-tasks",
    tags=["family-goal-integration"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/pending", response_model=list[TodayTaskItem])
def api_integration_pending(
    student_id: int,
    limit: int = Query(default=FAMILY_PENDING_LIST_DEFAULT_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[TodayTaskItem]:
    items = service.list_pending_occurrences(db, student_id=student_id, limit=limit)
    return [TodayTaskItem(**item) for item in items]


@router.get("/{occurrence_id}", response_model=TodayTaskItem)
def api_integration_detail(occurrence_id: int, db: Session = Depends(get_db)) -> TodayTaskItem:
    return TodayTaskItem(**call_or_http(service.get_occurrence_payload, db, occurrence_id=occurrence_id))


@router.post("/{occurrence_id}/approve", response_model=TodayTaskItem)
def api_integration_approve(occurrence_id: int, db: Session = Depends(get_db)) -> TodayTaskItem:
    current = call_or_http(service.get_occurrence_payload, db, occurrence_id=occurrence_id)
    reviewer_id = service.resolve_bound_parent_id(db, student_id=current["student_id"])
    call_or_http(
        service.review_occurrence,
        db,
        occurrence_id=occurrence_id,
        approve=True,
        reviewer_id=reviewer_id,
    )
    return TodayTaskItem(**service.get_occurrence_payload(db, occurrence_id=occurrence_id))


@router.post("/{occurrence_id}/reject", response_model=TodayTaskItem)
def api_integration_reject(
    occurrence_id: int,
    payload: ReviewOccurrenceRequest,
    db: Session = Depends(get_db),
) -> TodayTaskItem:
    current = call_or_http(service.get_occurrence_payload, db, occurrence_id=occurrence_id)
    reviewer_id = service.resolve_bound_parent_id(db, student_id=current["student_id"])
    call_or_http(
        service.review_occurrence,
        db,
        occurrence_id=occurrence_id,
        approve=False,
        reason=payload.reason,
        reviewer_id=reviewer_id,
    )
    return TodayTaskItem(**service.get_occurrence_payload(db, occurrence_id=occurrence_id))


@router.get("/students/{student_id}/rewards", response_model=RewardSummary)
def api_integration_rewards(student_id: int, db: Session = Depends(get_db)) -> RewardSummary:
    return RewardSummary(**service.reward_summary(db, student_id=student_id))
