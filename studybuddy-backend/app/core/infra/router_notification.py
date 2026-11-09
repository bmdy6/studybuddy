from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from .schemas.notification import NotificationItem, NotificationListResponse
from . import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
def api_list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationListResponse:
    items, unread_count = notification_service.list_notifications(db, user.id, unread_only=unread_only, limit=limit)
    return NotificationListResponse(items=items, unread_count=unread_count)


@router.patch("/{notification_id}/read", response_model=NotificationItem)
def api_mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationItem:
    item = notification_service.mark_notification_read(db, notification_id, user.id)
    if not item:
        raise HTTPException(status_code=404, detail="通知不存在")
    return item
