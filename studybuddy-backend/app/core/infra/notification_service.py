"""站内通知基础设施：通知 CRUD。

不依赖任何 feature（单向被 features 使用），属 core/infra 稳定底层。
学习计划提醒派发等业务编排见 features/p2/reminder_service.py。
"""
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import Notification
from .schemas.notification import NotificationItem


def _format_dt(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def to_item(notification: Notification) -> NotificationItem:
    return NotificationItem(
        id=notification.id,
        recipient_id=notification.recipient_id,
        student_id=notification.student_id,
        title=notification.title,
        content=notification.content,
        notification_type=notification.notification_type,
        source_type=notification.source_type,
        source_id=notification.source_id,
        read_at=_format_dt(notification.read_at),
        created_at=_format_dt(notification.created_at) or "",
    )


def list_notifications(db: Session, recipient_id: int, unread_only: bool = False, limit: int = 30) -> tuple[list[NotificationItem], int]:
    base = db.query(Notification).filter(Notification.recipient_id == recipient_id)
    unread_count = base.filter(Notification.read_at.is_(None)).count()
    query = base
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    items = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return [to_item(item) for item in items], unread_count


def mark_notification_read(db: Session, notification_id: int, recipient_id: int) -> NotificationItem | None:
    notification = db.get(Notification, notification_id)
    if not notification or notification.recipient_id != recipient_id:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now()
        db.commit()
        db.refresh(notification)
    return to_item(notification)


def create_notification_once(
    db: Session,
    *,
    recipient_id: int,
    student_id: int | None,
    title: str,
    content: str,
    notification_type: str,
    source_type: str,
    source_id: int | None,
    dedupe_key: str,
) -> tuple[NotificationItem | None, bool]:
    notification = Notification(
        recipient_id=recipient_id,
        student_id=student_id,
        title=title[:160],
        content=content,
        notification_type=notification_type,
        source_type=source_type,
        source_id=source_id,
        dedupe_key=dedupe_key[:120],
    )
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None, False
    db.refresh(notification)
    return to_item(notification), True
