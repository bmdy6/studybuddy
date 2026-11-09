from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GradingRule(Base):
    __tablename__ = "grading_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    rule_type: Mapped[str] = mapped_column(Enum("auto_exact", "auto_fuzzy", "manual"), nullable=False)
    matcher: Mapped[str] = mapped_column(
        Enum("exact", "regex", "float_tol", "levenshtein"),
        nullable=False,
        default="exact",
    )
    match_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
