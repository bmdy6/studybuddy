from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_teacher
from app.models.user import User
from .schemas.supervision import SupervisionSummaryResponse
from app.core.auth import access_service
from . import supervision_service


router = APIRouter(prefix="/api/students", tags=["supervision"])


@router.get("/{student_id}/supervision-summary", response_model=SupervisionSummaryResponse)
def api_get_supervision_summary(
    student_id: int,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> SupervisionSummaryResponse:
    if not access_service.teacher_can_access_student(db, teacher.id, student_id):
        raise HTTPException(status_code=403, detail="无权查看该学生督促摘要")
    return supervision_service.build_supervision_summary(db, student_id)
