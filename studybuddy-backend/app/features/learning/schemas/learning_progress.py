from datetime import date
from typing import Literal

from pydantic import BaseModel


class TodayProgress(BaseModel):
    completed_count: int
    total_count: int
    completion_rate: float | None
    status: Literal["no_plan", "planned", "completed"]


class DayProgress(BaseModel):
    record_date: date
    status: Literal["future", "no_plan", "planned", "active"]
    completed_count: int


class LearningProgressMetrics(BaseModel):
    student_id: int
    as_of: date
    today: TodayProgress
    streak_days: int
    week: list[DayProgress]
    recent_7_days_completed_tasks: int
