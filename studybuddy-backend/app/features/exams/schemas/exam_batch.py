"""考试批次 schemas：错题导入用。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreateBatchRequest(BaseModel):
    """创建考试批次（批量上传照片前先建批次）。"""

    student_id: int
    subject: str = Field(default="auto", max_length=20)
    exam_name: str = Field(max_length=100)
    exam_date: str = Field(max_length=20)  # YYYY-MM-DD


class BatchItem(BaseModel):
    """批次列表/详情项。"""

    id: int
    student_id: int
    subject: str
    exam_name: str
    exam_date: str
    photo_material_ids: list[int] = []
    parsed_pdf_ref: str | None = None
    folder_name: str | None = None
    status: str
    created_at: str


class ParsedQuestion(BaseModel):
    """视觉解析出的单题作答。"""

    no: str  # 题号
    answer: str  # 学生作答
    score: str | None = None  # 老师批改分数（无则 null）
    is_correct: bool | None = None  # 判分结果


class ParseResult(BaseModel):
    """视觉解析结果。"""

    batch_id: int
    questions: list[ParsedQuestion] = []
    raw_text: str = ""  # 模型原始返回


class PhotoAnswerReviewItem(BaseModel):
    """拍题识别后，学生逐题核对的作答项。"""

    question_no: str
    detected_answer: str | None = None
    confirmed_answer: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    needs_review: bool = True
    review_reason: str | None = None
    answer_type: Literal["choice", "text", "unknown"] = "unknown"
    source_excerpt: str | None = None
    skipped: bool = False


class PhotoAnswerReviewState(BaseModel):
    """拍题逐题核对状态，保存在批次上。"""

    batch_id: int
    recognized_markdown: str
    items: list[PhotoAnswerReviewItem] = []
    status: Literal["pending_review", "confirmed", "graded"] = "pending_review"
    confirmed_at: datetime | None = None


class ConfirmAnswerReviewRequest(BaseModel):
    """学生确认或修正拍题作答。"""

    items: list[PhotoAnswerReviewItem]


class GradeBatchRequest(BaseModel):
    """错题批次判分入库请求。"""

    grade_mode: Literal["has_score", "no_score_has_answer", "no_score_no_answer"] = "no_score_no_answer"
    manual_scores: dict[str, int] | None = None
    standard_answers: dict[str, str] | None = None
    parsed_questions: list[ParsedQuestion] = []
