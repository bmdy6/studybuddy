from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_teacher
from app.models.user import User
from .schemas.exam import (
    ExamAssignmentItem,
    ExamAssignmentRequest,
    ExamDetailResponse,
    ExamImportRequest,
    ExamImportResponse,
    ExamListItem,
    ExamStatusRequest,
)
from .service import (
    assign_exam,
    cancel_exam_assignment,
    get_exam_detail,
    import_exam,
    list_exam_assignments,
    list_exams,
    update_exam_status,
)

router = APIRouter(prefix="/api/exam", tags=["exam"])


@router.post("/import", response_model=ExamImportResponse, status_code=201)
def api_import_exam(
    req: ExamImportRequest,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> ExamImportResponse:
    return import_exam(db, req, teacher.id)


@router.get("/{exam_id}", response_model=ExamDetailResponse)
def api_get_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExamDetailResponse:
    try:
        return get_exam_detail(db, exam_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=list[ExamListItem])
def api_list_exams(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ExamListItem]:
    return list_exams(db, user)


@router.patch("/{exam_id}/status", response_model=ExamListItem)
def api_update_exam_status(
    exam_id: int,
    req: ExamStatusRequest,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> ExamListItem:
    try:
        return update_exam_status(db, exam_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{exam_id}/assignments", response_model=list[ExamAssignmentItem], status_code=201)
def api_assign_exam(
    exam_id: int,
    req: ExamAssignmentRequest,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> list[ExamAssignmentItem]:
    try:
        return assign_exam(db, exam_id, teacher.id, req)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{exam_id}/assignments", response_model=list[ExamAssignmentItem])
def api_list_exam_assignments(
    exam_id: int,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> list[ExamAssignmentItem]:
    try:
        return list_exam_assignments(db, exam_id, teacher.id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{exam_id}/assignments/{assignment_id}", status_code=204)
def api_cancel_exam_assignment(
    exam_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> None:
    try:
        cancel_exam_assignment(db, exam_id, assignment_id, teacher.id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
