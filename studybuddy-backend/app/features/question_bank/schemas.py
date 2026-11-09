from pydantic import BaseModel, Field


class SearchPaperSourcesRequest(BaseModel):
    province: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    district: str | None = Field(default=None, max_length=80)
    school: str | None = Field(default=None, max_length=120)
    grade: str = Field(max_length=50)
    semester: str | None = Field(default=None, max_length=50)
    subject: str = Field(max_length=50)
    textbook_version: str | None = Field(default=None, max_length=80)
    exam_type: str | None = Field(default=None, max_length=50)
    year: int | None = None
    limit: int = Field(default=8, ge=1, le=20)


class CreatePaperSourceRequest(BaseModel):
    title: str = Field(max_length=300)
    source_url: str = Field(max_length=2000)
    snippet: str | None = None
    province: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    district: str | None = Field(default=None, max_length=80)
    school: str | None = Field(default=None, max_length=120)
    grade: str = Field(max_length=50)
    semester: str | None = Field(default=None, max_length=50)
    subject: str = Field(max_length=50)
    textbook_version: str | None = Field(default=None, max_length=80)
    exam_type: str | None = Field(default=None, max_length=50)
    year: int | None = None
    source_adapter: str = Field(default="manual_entry", max_length=50)


class UpdatePaperSourceRequest(BaseModel):
    status: str = Field(pattern="^(candidate|confirmed|rejected|internal_style)$")


class QuestionBankPaperItem(BaseModel):
    id: int
    title: str
    source_url: str
    snippet: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    school: str | None = None
    grade: str | None = None
    semester: str | None = None
    subject: str | None = None
    textbook_version: str | None = None
    year: int | None = None
    exam_type: str | None = None
    source_type: str
    availability_level: str
    risk_level: str
    status: str
    confidence: int
    source_adapter: str | None = None
    review: dict | None = None


class ReviewPaperSourceRequest(BaseModel):
    use_ai: bool = False


class QuestionBankPaperReview(BaseModel):
    verdict: str
    confidence: int
    completeness: str
    suggested_status: str
    evidence: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    checked_at: str


class QuestionBankReviewBreakdown(BaseModel):
    verdict: str
    total_count: int
    sampled_count: int
    agreement_count: int
    confirmed_count: int
    rejected_count: int
    internal_style_count: int
    candidate_count: int


class QuestionBankReviewMetrics(BaseModel):
    total_reviewed: int
    sampled_count: int
    agreement_count: int
    agreement_rate: float | None = None
    formal_ready_sampled_count: int
    formal_ready_false_positive_count: int
    formal_ready_false_positive_rate: float | None = None
    reject_sampled_count: int
    reject_false_negative_count: int
    reject_false_negative_rate: float | None = None
    min_sample_size: int
    max_formal_ready_false_positive_rate: float
    auto_approve_allowed: bool
    verdict_breakdown: list[QuestionBankReviewBreakdown]


class QuestionBankItem(BaseModel):
    id: int
    subject: str | None = None
    grade: str | None = None
    semester: str | None = None
    question_type: str
    stem: str
    options: list | None = None
    answer: str | None = None
    explanation: str | None = None
    knowledge_tags: list = Field(default_factory=list)
    difficulty: str | None = None
    status: str
    duplicate_key: str


class ParsePaperSourceResponse(BaseModel):
    paper_id: int
    parsed_count: int
    saved_count: int
    items: list[QuestionBankItem]
    warnings: list[str] = Field(default_factory=list)


class PaperSourceFullPreviewResponse(BaseModel):
    paper_id: int
    status: str
    content_kind: str
    title: str
    message: str
    source_url: str
    final_url: str | None = None
    text: str | None = None
    text_length: int = 0
    question_count_estimate: int = 0
    last_question_no: str | None = None
    has_answer_signal: bool = False
    can_parse: bool = False
    warnings: list[str] = Field(default_factory=list)


class ValidateUploadedPaperFileResponse(BaseModel):
    filename: str
    content_type: str | None = None
    source_type: str
    content_length: int
    text_length: int
    question_count_estimate: int
    last_question_no: str | None = None
    has_answer_signal: bool
    can_parse_text: bool
    suggested_status: str
    warnings: list[str] = Field(default_factory=list)
    preview_text: str | None = None


class UploadedPaperSourceResponse(BaseModel):
    paper: QuestionBankPaperItem
    validation: ValidateUploadedPaperFileResponse


class UpdateQuestionBankItemRequest(BaseModel):
    status: str = Field(pattern="^(pending|approved|rejected)$")


class SearchPaperSourcesResponse(BaseModel):
    queries: list[str]
    saved_count: int
    candidates: list[QuestionBankPaperItem]
