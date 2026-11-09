from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    recipient_id: int
    student_id: int | None = None
    title: str
    content: str
    notification_type: str
    source_type: str
    source_id: int | None = None
    read_at: str | None = None
    created_at: str


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int


class DispatchStudyPlanReminderResponse(BaseModel):
    created_count: int
    skipped_count: int
    notifications: list[NotificationItem]
