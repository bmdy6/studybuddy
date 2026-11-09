from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_student, require_teacher
from app.models.user import User
from .schemas.answer import (
    CleanupStaleExamRecordsResponse,
    ExamRecordResult,
    GradeManualRequest,
    GradeManualResponse,
    PendingGradeItem,
    StartExamResponse,
    SubmitRequest,
    SubmitResponse,
)
from .grading_service import cleanup_stale_exam_records, get_exam_record_result, grade_manually, list_pending_grades, start_exam, submit_exam

router = APIRouter(tags=["answer"])


@router.post("/api/exam/{exam_id}/start", response_model=StartExamResponse, status_code=201)
def api_start_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> StartExamResponse:
    try:
        return start_exam(db, exam_id, student.id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/exam/{exam_id}/submit", response_model=SubmitResponse)
def api_submit(
    exam_id: int,
    req: SubmitRequest,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> SubmitResponse:
    try:
        return submit_exam(db, exam_id, req, student.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/exam-record/{record_id}/result", response_model=ExamRecordResult)
def api_exam_record_result(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExamRecordResult:
    try:
        return get_exam_record_result(db, record_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/answers/pending", response_model=list[PendingGradeItem])
def api_pending(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> list[PendingGradeItem]:
    return list_pending_grades(db, limit)


@router.delete("/api/exam-records/stale", response_model=CleanupStaleExamRecordsResponse)
def api_cleanup_stale_exam_records(
    older_than_hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> CleanupStaleExamRecordsResponse:
    del teacher
    deleted_count, deleted_ids = cleanup_stale_exam_records(db, older_than_hours=older_than_hours, limit=limit)
    return CleanupStaleExamRecordsResponse(
        deleted_count=deleted_count,
        deleted_record_ids=deleted_ids,
        older_than_hours=older_than_hours,
    )


@router.post("/api/answer/{answer_id}/grade", response_model=GradeManualResponse)
def api_grade(
    answer_id: int,
    req: GradeManualRequest,
    db: Session = Depends(get_db),
    teacher: User = Depends(require_teacher),
) -> GradeManualResponse:
    try:
        return grade_manually(db, answer_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
