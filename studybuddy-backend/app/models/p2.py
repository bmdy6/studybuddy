"""P2.1 数据模型：兴趣、反馈、推荐、属性面板。"""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StudentInterest(Base):
    """学生兴趣标签：学生确认后才进入正式画像。"""

    __tablename__ = "student_interests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tag: Mapped[str] = mapped_column(String(64), nullable=False, comment="兴趣标签如 篮球/天文")
    source: Mapped[str] = mapped_column(Enum("manual", "inferred"), nullable=False, default="manual")
    approved: Mapped[bool] = mapped_column(default=True, comment="学生是否确认")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LearningFeedback(Base):
    """学习反馈（时长/资源观看/自评/困难）。"""

    __tablename__ = "learning_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(Enum("duration", "resource_view", "self_assess", "difficulty"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    related_resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # naive UTC：aggregate_daily_facts 用 naive UTC 窗口对 LearningFeedback.created_at 求时长；
    # server_default=func.now()=MySQL NOW()，CST session 下写本地会落不进当日窗口。
    # microsecond=0 避免 DATETIME 秒级四舍五入进位越过 utc_end(详见 completed_at 注释)。
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))


class ResourceRecommendation(Base):
    """资源推荐（B站等外部链接）。"""

    __tablename__ = "resource_recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="bilibili")
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_interests: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    related_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    clicked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RecommendationBoundary(Base):
    """家长设置的资源推荐边界。"""

    __tablename__ = "recommendation_boundaries"
    __table_args__ = (UniqueConstraint("student_id", name="uk_recommendation_boundary_student"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    allowed_platforms: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    blocked_keywords: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    allow_entertainment_interests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class StudentAttribute(Base):
    """属性快照（初始化/做题触发/手动，保留历史成长曲线）。"""

    __tablename__ = "student_attributes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="{chinese,math,english,pe,engagement,mastered_count}")
    source: Mapped[str] = mapped_column(Enum("init", "exam_graded", "manual"), nullable=False)
    trigger_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="触发源如 exam_record_id")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StudyPlan(Base):
    """学习计划：由学生或家长通过 Agent 生成，拆成可执行任务。"""

    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    focus: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="计划目标/关注点")
    status: Mapped[str] = mapped_column(Enum("active", "completed", "archived"), nullable=False, default="active")
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="计划完整说明")
    context_refs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="来源上下文引用")
    source_plan_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("study_plans.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        comment="沿用旧计划时的来源计划 id",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="乐观锁版本号")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class StudyPlanItem(Base):
    """学习计划项：15-30 分钟一格，支持学生反馈完成。"""

    __tablename__ = "study_plan_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    status: Mapped[str] = mapped_column(Enum("todo", "in_progress", "done", "skipped"), nullable=False, default="todo")
    related_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StudyPlanItemAttempt(Base):
    """学习计划项的完成判定记录（U-044）：AI 评估学生作答后写的 attempt。

    一次完成尝试对应一条记录，assessment 标记结果，evidence_summary 摘录证据。
    """

    __tablename__ = "study_plan_item_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("study_plan_items.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assessment: Mapped[str] = mapped_column(Enum("passed", "needs_retry", "blocked"), nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    taught_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
