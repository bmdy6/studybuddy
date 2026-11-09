from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyLearningRecord(Base):
    """每日学习记录：一名学生一天一条的事实与摘要容器（spec 3.1）。

    证据聚合、evidence_hash 计算、AI 摘要生成不在本实体职责内（PR-03/04），
    本表只提供唯一约束保护的事实容器和状态字段。
    """

    __tablename__ = "daily_learning_records"
    __table_args__ = (
        UniqueConstraint("student_id", "mode", "record_date", name="uk_daily_learning_records_student_mode_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # generation_status: pending / generating / ready / failed（SQL 层用 ENUM，ORM 用 String 映射）
    generation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # summary_source: ai / deterministic / NULL（未生成）
    summary_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # checkin_status: pending / done / NULL（未启用对齐）
    checkin_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    checkin_response: Mapped[str | None] = mapped_column(String(50), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
