from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from app.core.auth import access_service
from app.core.infra.schemas.notification import DispatchStudyPlanReminderResponse
from . import reminder_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/study-plan-reminders/dispatch", response_model=DispatchStudyPlanReminderResponse)
def api_dispatch_study_plan_reminders(
    student_id: int | None = Query(default=None, description="家长可指定绑定学生；不传则发送全部绑定学生"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DispatchStudyPlanReminderResponse:
    if user.role == "student":
        student_ids = [resolve_accessible_student_id(db, user, student_id)]
    elif student_id is not None:
        student_ids = [resolve_accessible_student_id(db, user, student_id)]
    else:
        student_ids = [student.id for student in access_service.list_accessible_students(db, user.id)]
    return reminder_service.dispatch_study_plan_reminder_notifications(db, student_ids=student_ids, limit=limit)
