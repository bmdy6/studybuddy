from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exam_record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exam_records.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    is_correct: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0/1/NULL(未判)
    is_manual_graded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    manual_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
