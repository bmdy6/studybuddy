"""家庭目标与任务激励请求/响应契约。

金额统一用字符串（"5.00"）对外，避免前端拿到 float 出现 5.0/5.000000001 这类展示噪声。
"""

from datetime import date

from pydantic import BaseModel, Field


class CreateGoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    description: str | None = None
    reward_amount: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class UpdateGoalRequest(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    description: str | None = None
    reward_amount: str | None = None
    status: str | None = None


class GoalItem(BaseModel):
    id: int
    student_id: int
    title: str
    description: str | None = None
    reward_amount: str | None = None
    creator_role: str
    status: str
    start_date: date | None = None
    end_date: date | None = None
    created_at: str | None = None


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = None
    repeat_type: str = "once"
    reward_amount: str | None = None
    sort_order: int = 0


class UpdateTaskRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    description: str | None = None
    repeat_type: str | None = None
    reward_amount: str | None = None
    status: str | None = None
    sort_order: int | None = None


class TaskItem(BaseModel):
    id: int
    goal_id: int
    student_id: int
    title: str
    description: str | None = None
    repeat_type: str
    reward_amount: str | None = None
    resolved_reward_amount: str | None = None
    status: str
    sort_order: int


class EvidenceItem(BaseModel):
    id: int
    url: str
    sort_order: int


class TodayTaskItem(BaseModel):
    occurrence_id: int
    task_id: int
    goal_id: int
    student_id: int
    title: str
    description: str | None = None
    goal_title: str
    repeat_type: str
    status: str
    occurrence_date: str
    reward_amount: str | None = None
    submit_note: str | None = None
    reject_reason: str | None = None
    submitted_at: str | None = None
    reviewed_at: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class SubmitOccurrenceRequest(BaseModel):
    note: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ReviewOccurrenceRequest(BaseModel):
    reason: str | None = None


class EvidenceUploadResponse(BaseModel):
    content_ref: str
    url: str


class RewardRecordItem(BaseModel):
    id: int
    occurrence_id: int
    task_title: str
    goal_title: str | None = None
    amount: str
    confirmed_at: str | None = None


class FamilyGoalContext(BaseModel):
    """家庭任务上下文：孩子有没有能确认作业的家长账号。"""

    parent_bound: bool


class RewardSummary(BaseModel):
    student_id: int
    total_amount: str
    records: list[RewardRecordItem] = Field(default_factory=list)
