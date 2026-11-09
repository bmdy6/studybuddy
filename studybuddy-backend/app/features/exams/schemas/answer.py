from pydantic import BaseModel, field_validator


class AnswerSubmit(BaseModel):
    question_id: int
    student_answer: str


class SubmitRequest(BaseModel):
    exam_record_id: int
    answers: list[AnswerSubmit]


class SubmitResponse(BaseModel):
    exam_record_id: int
    status: str
    objective_score: float
    pending_manual_count: int


class ExamRecordAnswerResult(BaseModel):
    answer_id: int
    question_id: int
    question_stem: str
    question_type: str
    student_answer: str
    correct_answer: str | None
    is_correct: bool | None
    score: float | None
    max_score: float
    graded: bool
    knowledge_tags: list[str]


class ExamRecordResult(BaseModel):
    exam_record_id: int
    exam_id: int
    exam_title: str
    status: str
    total_score: float | None
    feedback_mode: str
    answers: list[ExamRecordAnswerResult]


class StartExamResponse(BaseModel):
    exam_record_id: int
    exam_id: int
    status: str


class CleanupStaleExamRecordsResponse(BaseModel):
    deleted_count: int
    deleted_record_ids: list[int]
    older_than_hours: int


class PendingGradeItem(BaseModel):
    answer_id: int
    exam_record_id: int
    student_name: str
    exam_title: str
    question_id: int
    question_stem: str
    question_type: str
    max_score: float
    student_answer: str
    reference_answer: str
    submitted_at: str


class GradeManualRequest(BaseModel):
    manual_score: float
    manual_comment: str = ""

    @field_validator("manual_score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if v < 0:
            raise ValueError("manual_score 不能为负")
        return v


class GradeManualResponse(BaseModel):
    answer_id: int
    graded: bool
    score: float
    is_correct: bool
    graded_at: str
