from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .schemas.learning_map import LearningMapResponse
from .map_service import build_learning_map

router = APIRouter(prefix="/api/students", tags=["learning-map"])


@router.get("/{student_id}/learning-map", response_model=LearningMapResponse)
def api_learning_map(
    student_id: int,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningMapResponse:
    """学生或绑定家长查看学习地图。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    return build_learning_map(db, sid, limit=limit)
