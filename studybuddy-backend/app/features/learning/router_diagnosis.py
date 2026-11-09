from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.constants import DIAGNOSIS_TOP_N
from app.database import get_db
from app.deps import get_current_user, require_teacher, resolve_accessible_student_id
from app.models.user import User
from .schemas.diagnosis import DiagnosisResponse
from app.core.auth import access_service
from .diagnosis_service import get_diagnoses, get_diagnosis

router = APIRouter(prefix="/api/diagnosis", tags=["diagnosis"])


@router.get("/{student_id}", response_model=DiagnosisResponse)
def api_diagnosis(
    student_id: int,
    top_n: int = Query(DIAGNOSIS_TOP_N, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiagnosisResponse:
    """学生查自己诊断；老师查任意学生。学生只能查自己。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    try:
        return get_diagnosis(db, sid, top_n)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=list[DiagnosisResponse])
def api_diagnosis_all(
    top_n: int = Query(DIAGNOSIS_TOP_N, ge=1, le=50),
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> list[DiagnosisResponse]:
    """老师查已绑定学生诊断（批拉，避免 N+1 查询放大）。"""
    students = access_service.list_accessible_students(db, teacher.id)
    return get_diagnoses(db, [s.id for s in students], top_n)
