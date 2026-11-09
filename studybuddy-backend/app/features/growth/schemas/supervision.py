from pydantic import BaseModel, Field


class SupervisionReminderItem(BaseModel):
    plan_id: int
    title: str
    planned_date: str | None = None
    is_overdue: bool
    overdue_days: int
    todo_count: int
    todo_minutes: int
    first_todo_title: str
    reminder_message: str


class SupervisionSupportItem(BaseModel):
    note_id: int
    title: str
    content: str
    created_at: str


class SupervisionWeakPointItem(BaseModel):
    tag: str
    status: str
    error_count: int
    last_wrong_at: str | None = None
    next_action: str


class SupervisionAssignmentItem(BaseModel):
    assignment_id: int
    exam_id: int
    exam_title: str
    status: str
    due_at: str | None = None
    note: str | None = None
    created_at: str


class WeeklyReportDraft(BaseModel):
    title: str = "本周学习情况草稿"
    is_empty: bool = False
    summary: str
    highlights: list[str] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class SupervisionSummaryResponse(BaseModel):
    student_id: int
    student_name: str | None = None
    reminders: list[SupervisionReminderItem] = Field(default_factory=list)
    support_items: list[SupervisionSupportItem] = Field(default_factory=list)
    weak_points: list[SupervisionWeakPointItem] = Field(default_factory=list)
    recent_assignments: list[SupervisionAssignmentItem] = Field(default_factory=list)
    weekly_report: WeeklyReportDraft
