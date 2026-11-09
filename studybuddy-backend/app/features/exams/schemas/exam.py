"""试卷导入、查询与定向分发的 Pydantic schemas。

★ 安全红线：响应模型（QuestionResponse / ExamDetailResponse / ExamListItem）
  绝不包含 answer_json 字段，防止标准答案下发客户端。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, field_validator


class QuestionType(str, Enum):
    single_choice = "single_choice"
    multi_choice = "multi_choice"
    fill_blank = "fill_blank"
    transform = "transform"
    translation = "translation"
    essay = "essay"
    math_answer = "math_answer"


class GradingInput(BaseModel):
    rule_type: str
    matcher: str = "exact"
    match_params: dict[str, Any] = {}

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in ("auto_exact", "auto_fuzzy", "manual"):
            raise ValueError(f"不支持的 rule_type: {v}，可选：auto_exact/auto_fuzzy/manual")
        return v

    @field_validator("matcher")
    @classmethod
    def validate_matcher(cls, v: str) -> str:
        if v not in ("exact", "regex", "float_tol", "levenshtein"):
            raise ValueError(f"不支持的 matcher: {v}")
        return v


class QuestionInput(BaseModel):
    type: QuestionType
    stem: str
    options: Optional[list[str]] = None
    answer: Any  # 标准答案，存 answer_json 列
    score: float
    knowledge_tags: list[str] = []
    group_id: Optional[str] = None
    grading: GradingInput

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("score 必填且 > 0")
        return v


class ExamImportRequest(BaseModel):
    schema_version: int = 1
    title: str
    subject: str
    feedback_mode: str = "after_submit"
    shuffle_groups: bool = False
    questions: list[QuestionInput]

    @field_validator("feedback_mode")
    @classmethod
    def validate_feedback_mode(cls, v: str) -> str:
        if v not in ("immediate", "after_submit", "hidden"):
            raise ValueError(f"不支持的 feedback_mode: {v}")
        return v


class ExamAssignmentRequest(BaseModel):
    student_ids: list[int]
    due_at: datetime | None = None
    note: str | None = None


class ExamAssignmentItem(BaseModel):
    id: int
    exam_id: int
    student_id: int
    student_name: str
    status: str
    due_at: str | None = None
    note: str | None = None


# ===== 响应模型（★ 绝不含 answer_json） =====


class QuestionResponse(BaseModel):
    id: int
    type: QuestionType
    stem: str
    options: Optional[list[str]] = None
    score: float
    group_id: Optional[str] = None
    # 没有 answer_json 字段


class ExamDetailResponse(BaseModel):
    id: int
    title: str
    feedback_mode: str
    questions: list[QuestionResponse]


class ExamStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("draft", "published", "archived"):
            raise ValueError(f"不支持的 status: {v}")
        return v


class ExamImportResponse(BaseModel):
    exam_id: int
    title: str
    question_count: int


class ExamListItem(BaseModel):
    id: int
    title: str
    subject: str
    status: str
    visibility: str | None = None
    assignment_status: str | None = None
    assignment_note: str | None = None
    assignment_due_at: str | None = None
    question_count: int
    total_score: float
    has_new: bool = False
    created_at: str
    latest_record_status: str | None = None
    latest_record_id: int | None = None
