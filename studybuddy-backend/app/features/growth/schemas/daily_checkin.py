"""每日学习对齐接口契约。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CheckinChoiceKey = Literal["follow_plan", "adjust", "reduce"]
CheckinStatus = Literal["yesterday_completed", "yesterday_incomplete", "consecutive_incomplete", "no_plan", "already_done"]


class DailyCheckinChoice(BaseModel):
    key: CheckinChoiceKey
    label: str


class DailyCheckinRequest(BaseModel):
    """兼容 choice/response 两个客户端命名，最终只接受一个快捷选择。"""

    choice: CheckinChoiceKey | None = None
    response: CheckinChoiceKey | None = None
    key: CheckinChoiceKey | None = None

    @model_validator(mode="after")
    def require_choice(self) -> "DailyCheckinRequest":
        if self.choice is None and self.response is None and self.key is None:
            raise ValueError("请选择一个每日对齐选项")
        return self

    @property
    def selected_choice(self) -> CheckinChoiceKey:
        return self.choice or self.response or self.key  # type: ignore[return-value]


class DailyCheckinStatus(BaseModel):
    record_date: date
    status: CheckinStatus
    state: CheckinStatus
    message: str
    task_count: int = Field(ge=0)
    estimated_minutes: int = Field(ge=0)
    unfinished_days: int = Field(default=0, ge=0)
    primary_action: CheckinChoiceKey | None = None
    primary_recommendation: CheckinChoiceKey | None = None
    choices: list[DailyCheckinChoice]
    checkin_status: str | None = None
    checkin_response: str | None = None
    checked_in_at: datetime | None = None
