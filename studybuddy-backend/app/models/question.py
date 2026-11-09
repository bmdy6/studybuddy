from decimal import Decimal
from typing import Any

from sqlalchemy import DECIMAL, JSON, BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(
        Enum(
            "single_choice",
            "multi_choice",
            "fill_blank",
            "transform",
            "translation",
            "essay",
            "math_answer",
        ),
        nullable=False,
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    answer_json: Mapped[Any] = mapped_column(JSON, nullable=False)  # ★标准答案，永不下发客户端
    score: Mapped[Decimal] = mapped_column(DECIMAL(5, 2), nullable=False)
    knowledge_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
