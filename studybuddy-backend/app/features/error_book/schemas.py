from pydantic import BaseModel, Field


class ErrorQuestionItem(BaseModel):
    error_id: int
    question_id: int
    stem: str
    student_answer: str
    correct_answer: str
    error_count: int
    knowledge_tags: list[str] = Field(default_factory=list)


class ErrorGroup(BaseModel):
    tag: str
    error_count: int
    last_wrong_at: str
    questions: list[ErrorQuestionItem]


class ErrorTypeGroup(BaseModel):
    """题型分组（学科下一级）。"""

    question_type: str
    type_label: str
    error_count: int
    last_wrong_at: str
    questions: list[ErrorQuestionItem]


class ErrorSubjectGroup(BaseModel):
    """学科分组（错题本页顶层：语数英…）。"""

    subject: str
    total_count: int
    type_groups: list[ErrorTypeGroup]
