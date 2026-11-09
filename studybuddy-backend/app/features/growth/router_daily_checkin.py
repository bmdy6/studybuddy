"""每日对齐状态与快捷选择 API。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .schemas.daily_checkin import DailyCheckinRequest, DailyCheckinStatus
from . import checkin_service as daily_checkin_service

router = APIRouter(prefix="/api/daily-checkin", tags=["daily-checkin"])


@router.get("", response_model=DailyCheckinStatus)
def get_daily_checkin(
    student_id: int | None = None,
    as_of: date | None = Query(default=None, description="仅供历史状态查询，默认服务端本地日期"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyCheckinStatus:
    sid = resolve_accessible_student_id(db, user, student_id)
    return daily_checkin_service.get_status(db, sid, target_date=as_of)


@router.post("", response_model=DailyCheckinStatus)
def submit_daily_checkin(
    request: DailyCheckinRequest,
    student_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyCheckinStatus:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="只有学生可以提交每日对齐")
    sid = resolve_accessible_student_id(db, user, student_id)
    try:
        return daily_checkin_service.submit(db, sid, request.selected_choice)
    except daily_checkin_service.CheckinAlreadyCompletedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
