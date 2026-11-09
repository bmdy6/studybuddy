from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .schemas import ErrorGroup, ErrorSubjectGroup
from .service import get_error_book, get_error_book_by_subject

router = APIRouter(prefix="/api/error-book", tags=["error_book"])


def _resolve_target(db: Session, user: User, student_id: int | None) -> int:
    """学生查自己；老师须指定 student_id。"""
    return resolve_accessible_student_id(db, user, student_id)


@router.get("", response_model=list[ErrorGroup])
def api_error_book(
    tag: str | None = Query(None),
    student_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ErrorGroup]:
    """学生查自己的错题本；老师可指定 student_id 查任意学生。（按知识点 tag 分组）"""
    return get_error_book(db, _resolve_target(db, user, student_id), tag)


@router.get("/by-subject", response_model=list[ErrorSubjectGroup])
def api_error_book_by_subject(
    student_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ErrorSubjectGroup]:
    """错题本页用：学科 → 题型 两级分组。"""
    return get_error_book_by_subject(db, _resolve_target(db, user, student_id))
