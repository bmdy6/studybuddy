"""P2.1 schemas：兴趣/反馈/推荐/属性。"""

from pydantic import BaseModel, Field


class InterestItem(BaseModel):
    id: int
    tag: str
    source: str
    approved: bool


class AddInterestRequest(BaseModel):
    tag: str
    source: str = "manual"


class UpdateInterestRequest(BaseModel):
    approved: bool = True


class FeedbackItem(BaseModel):
    id: int
    feedback_type: str
    content: str
    created_at: str


class SubmitFeedbackRequest(BaseModel):
    feedback_type: str  # duration/resource_view/self_assess/difficulty
    content: str
    related_resource_id: int | None = None


class RecommendationItem(BaseModel):
    id: int
    title: str
    platform: str
    url: str
    reason: str | None = None
    clicked: bool


class RecommendationBoundaryItem(BaseModel):
    student_id: int
    allowed_platforms: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)
    daily_limit: int
    allow_entertainment_interests: bool = False


class UpdateRecommendationBoundaryRequest(BaseModel):
    allowed_platforms: list[str] = Field(default_factory=lambda: ["bilibili"])
    blocked_keywords: list[str] = Field(default_factory=list)
    daily_limit: int = Field(default=3, ge=0, le=20)
    allow_entertainment_interests: bool = False


class AttributeSnapshot(BaseModel):
    id: int
    snapshot: dict
    source: str
    trigger_ref: str | None = None
    created_at: str


class InitAttributesRequest(BaseModel):
    """初始化属性：录入大考成绩。"""

    exam_scores: dict[str, int]  # {"chinese": 85, "math": 90, "english": 78, "pe": 80}


class ProfileOnboardingRequest(BaseModel):
    """冷启动画像补全。"""

    grade: str | None = None
    semester: str | None = None
    school: str | None = None
    district: str | None = None
    textbook_versions: dict[str, str] = Field(default_factory=dict)
    recent_scores: dict[str, int] = Field(default_factory=dict)
    weak_subjects: list[str] = Field(default_factory=list)
    study_preferences: dict[str, object] = Field(default_factory=dict)
    interests: list[str] = Field(default_factory=list)


class UpdateProfileRequest(BaseModel):
    """画像增量更新：对话中学到明确事实时静默落库，只传变化字段。

    与 ProfileOnboardingRequest 区别：兴趣按增删传入（add/remove），不写学习反馈，
    不触碰能力分与 subject_sources 证据。
    """

    grade: str | None = None
    semester: str | None = None
    school: str | None = None
    district: str | None = None
    textbook_versions: dict[str, str] = Field(default_factory=dict)
    recent_scores: dict[str, int] = Field(default_factory=dict)
    weak_subjects: list[str] = Field(default_factory=list)
    study_preferences: dict[str, object] = Field(default_factory=dict)
    add_interests: list[str] = Field(default_factory=list)
    remove_interests: list[str] = Field(default_factory=list)


class ProfileSummary(BaseModel):
    """学生画像摘要和补全状态。"""

    student_id: int
    needs_onboarding: bool
    missing_fields: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class StudyPlanItemInput(BaseModel):
    title: str
    target: str | None = None
    minutes: int = 20
    related_tags: list[str] = Field(default_factory=list)


class CreateStudyPlanRequest(BaseModel):
    title: str
    focus: str | None = None
    description: str | None = None
    context_refs: dict | None = None
    planned_date: str | None = None
    items: list[StudyPlanItemInput]


class ConfirmPlanDraftRequest(BaseModel):
    revision: int
    student_id: int | None = None  # 学生不传(用自己)，家长需指定


class UpdateStudyPlanRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    planned_date: str | None = None
    revision: int


class UpdateStudyPlanItemRequest(BaseModel):
    status: str
    # 学生自助完成的证据（复述/回答摘要）。status=done 时必填（strip 后非空），
    # 由共享 service record_study_plan_item_assessment 校验，空白证据 422。
    evidence_summary: str | None = None


class StudyPlanItem(BaseModel):
    id: int
    title: str
    target: str | None = None
    minutes: int
    status: str
    related_tags: list[str] = Field(default_factory=list)
    sort_order: int
    completed_at: str | None = None


class StudyPlanItemDraft(BaseModel):
    title: str
    target: str | None = None
    minutes: int = 20
    related_tags: list[str] = Field(default_factory=list)


class StudyPlanItemUpdate(BaseModel):
    id: int
    status: str


class StudyPlanItemStatus(BaseModel):
    id: int
    status: str
    completed_at: str | None = None


class StudyPlan(BaseModel):
    id: int
    student_id: int
    mode: str = "study"
    title: str
    focus: str | None = None
    description: str | None = None
    context_refs: dict | None = None
    source_plan_id: int | None = None
    revision: int = 1
    status: str
    planned_date: str | None = None
    is_overdue: bool = False
    overdue_days: int = 0
    reminder_message: str | None = None
    created_by: int | None = None
    created_at: str
    items: list[StudyPlanItem] = Field(default_factory=list)


class StudyPlanReminder(BaseModel):
    plan_id: int
    student_id: int
    title: str
    planned_date: str | None = None
    is_overdue: bool
    overdue_days: int
    todo_count: int
    todo_minutes: int
    first_todo_title: str
    first_todo_item_id: int | None = None
    reminder_message: str
