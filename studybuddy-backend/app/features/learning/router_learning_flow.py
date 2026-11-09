from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .schemas.learning_flow import LearningFlowEntry
from .flow_service import get_learning_flow_entry, get_review_flow_entry

router = APIRouter(prefix="/api/learning-flow", tags=["learning-flow"])


@router.get("/entry", response_model=LearningFlowEntry)
def api_learning_flow_entry(
    student_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningFlowEntry:
    sid = resolve_accessible_student_id(db, user, student_id)
    return get_learning_flow_entry(db, sid)


@router.get("/review-entry", response_model=LearningFlowEntry)
def api_review_flow_entry(
    student_id: int | None = Query(None),
    error_id: int | None = Query(None, gt=0),
    knowledge_tag: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningFlowEntry:
    if (error_id is None) == (not (knowledge_tag or "").strip()):
        raise HTTPException(status_code=422, detail="必须且只能指定一道错题或一个知识点")
    sid = resolve_accessible_student_id(db, user, student_id)
    try:
        return get_review_flow_entry(
            db,
            sid,
            error_id=error_id,
            knowledge_tag=knowledge_tag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
