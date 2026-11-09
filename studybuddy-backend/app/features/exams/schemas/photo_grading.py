"""拍题批改 schemas。"""

from pydantic import BaseModel, Field


class PhotoGradingQuestion(BaseModel):
    """单题批改结果。"""

    no: str = ""
    stem: str = ""
    student_answer: str = ""
    correct_answer: str = ""
    is_correct: bool | None = None
    error_point: str = ""
    knowledge_tags: list[str] = Field(default_factory=list)
    explanation: str = ""
    confidence: str = "low"
    needs_review: bool = True


class PhotoGradingResult(BaseModel):
    """拍题批改结构化结果。"""

    subject: str = ""
    questions: list[PhotoGradingQuestion] = Field(default_factory=list)
    raw_text: str = ""
