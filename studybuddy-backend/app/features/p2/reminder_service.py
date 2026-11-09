"""学习计划提醒派发：把 due 的学习计划生成站内通知。

业务编排层：依赖 study_plan（同域 p2）+ access_service（core/auth）+ notification 基础设施（core/infra）。
单向依赖 core，不反向。与 study_plan 同域内聚（学习计划提醒是 study_plan 的派生行为）。
"""
from datetime import date

from sqlalchemy.orm import Session

from app.core.auth import access_service
from app.core.infra import notification_service
from app.core.infra.schemas.notification import DispatchStudyPlanReminderResponse
from app.models.user import User
from . import study_plan


def study_plan_reminder_dedupe_key(plan_id: int) -> str:
    return f"study-plan:{plan_id}:{date.today().isoformat()}"


def dispatch_study_plan_reminder_notifications(
    db: Session,
    *,
    student_ids: list[int] | None = None,
    limit: int = 200,
) -> DispatchStudyPlanReminderResponse:
    """把待提醒学习计划生成站内通知，可被 API 和定时脚本复用。"""
    # 站内通知批量派发：不过滤 mode（多学生混合模式都提醒，与站内列表口径一致）
    reminders = study_plan.list_due_study_plan_reminders(db, student_ids, limit=limit, mode=None)
    created: list = []
    skipped_count = 0
    for reminder in reminders:
        bound_teachers = access_service.list_bound_teachers(db, reminder.student_id)
        recipients = [reminder.student_id, *[teacher.id for teacher in bound_teachers]]
        for recipient_id in dict.fromkeys(recipients):
            item, did_create = notification_service.create_notification_once(
                db,
                recipient_id=recipient_id,
                student_id=reminder.student_id,
                title="学习计划提醒",
                content=reminder.reminder_message,
                notification_type="study_plan_reminder",
                source_type="study_plan",
                source_id=reminder.plan_id,
                dedupe_key=study_plan_reminder_dedupe_key(reminder.plan_id),
            )
            if did_create and item:
                created.append(item)
            else:
                skipped_count += 1
    return DispatchStudyPlanReminderResponse(created_count=len(created), skipped_count=skipped_count, notifications=created)


def dispatch_all_study_plan_reminder_notifications(db: Session, *, limit: int = 200) -> DispatchStudyPlanReminderResponse:
    student_ids = [row.id for row in db.query(User.id).filter(User.role == "student").order_by(User.id.asc()).all()]
    return dispatch_study_plan_reminder_notifications(db, student_ids=student_ids, limit=limit)
