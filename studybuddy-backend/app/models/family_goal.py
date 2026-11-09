"""家庭目标与任务激励模型。

五张表构成一条闭环：目标 -> 任务 -> 任务实例（occurrence）-> 图片证据 -> 奖励记录。
金额只记录在目标/任务/奖励记录上，不建钱包与余额字段；累计奖励由 SUM(amount) 得出。

设计要点（详见 docs/11-功能/[部分实施]家庭目标-任务激励与奖励记录.md）：
- occurrence 的 UNIQUE(task_id, occurrence_date) 是「惰性生成每日任务实例」的幂等保险；
- family_reward_records.occurrence_id 唯一键是「重复打勾不重复发奖」的第二道保险；
- reward_amount_snapshot 在审核确认时写入，之后改任务金额不影响历史记录。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FamilyGoal(Base):
    """家庭目标：孩子自己想完成的，或家长给孩子定的。"""

    __tablename__ = "family_goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 目标级默认奖励金额；任务级为空时继承。可以两者都为空（目标先立、金额后补）。
    reward_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    # 谁创建的：student=孩子自己 / parent=家长给孩子定的（后端 role=teacher 即家长）
    creator_role: Mapped[str] = mapped_column(Enum("student", "parent"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "archived"), nullable=False, default="active", server_default="active"
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FamilyGoalTask(Base):
    """目标下的任务：一次性或每日重复。"""

    __tablename__ = "family_goal_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_goals.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repeat_type: Mapped[str] = mapped_column(
        Enum("once", "daily"), nullable=False, default="once", server_default="once"
    )
    # 为空则继承 family_goals.reward_amount
    reward_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "archived"), nullable=False, default="active", server_default="active"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FamilyTaskOccurrence(Base):
    """任务实例：一次待完成/待确认/已确认的任务，一次完成对应一条。"""

    __tablename__ = "family_task_occurrences"
    __table_args__ = (
        UniqueConstraint("task_id", "occurrence_date", name="uk_family_task_occurrences_task_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_goal_tasks.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    # pending=待完成 / submitted=待家长确认 / approved=已确认 / rejected=已驳回（可重交）
    status: Mapped[str] = mapped_column(
        Enum("pending", "submitted", "approved", "rejected"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    submit_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 审核确认时的金额快照，历史记录不随任务金额改动
    reward_amount_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FamilyTaskEvidence(Base):
    """完成证据：只保存图片文件引用（COS key 或 local: 相对路径），不做任何识别判断。"""

    __tablename__ = "family_task_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurrence_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("family_task_occurrences.id"), nullable=False
    )
    content_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FamilyRewardRecord(Base):
    """奖励记录：家长确认后生成一条，occurrence_id 唯一保证不重复发奖。"""

    __tablename__ = "family_reward_records"
    __table_args__ = (
        UniqueConstraint("occurrence_id", name="uk_family_reward_records_occurrence"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    occurrence_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("family_task_occurrences.id"), nullable=False
    )
    # 任务/目标标题快照，用于「默写英语单词 +¥5」这类展示
    task_title: Mapped[str] = mapped_column(String(160), nullable=False)
    goal_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
