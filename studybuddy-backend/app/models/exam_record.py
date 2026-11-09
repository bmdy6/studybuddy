from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExamRecord(Base):
    __tablename__ = "exam_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("in_progress", "submitted", "graded"),
        nullable=False,
        default="in_progress",
    )
    total_score: Mapped[Decimal | None] = mapped_column(DECIMAL(6, 2), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # MVP-B：疑似敷衍/乱点/空提交标记（门禁判定后置 1，正常为 0）
    suspected_low_quality: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
