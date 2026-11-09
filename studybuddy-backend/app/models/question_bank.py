from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QuestionBankPaper(Base):
    """项目级题库的原始试卷/候选来源。

    这是题库资产的入口层：先沉淀来源，再做解析、审核和正式入题库。
    """

    __tablename__ = "question_bank_papers"
    __table_args__ = (UniqueConstraint("source_url_hash", name="uk_qb_paper_source_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    province: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(50), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    textbook_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    source_type: Mapped[str] = mapped_column(
        Enum("school_paper", "district_paper", "web_paper", "paid_or_unclear", "ai_generated", "search_result"),
        nullable=False,
        default="search_result",
    )
    availability_level: Mapped[str] = mapped_column(Enum("A", "B", "C", "D"), nullable=False, default="B")
    risk_level: Mapped[str] = mapped_column(Enum("low", "medium", "high"), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(Enum("candidate", "confirmed", "rejected", "internal_style"), nullable=False, default="candidate")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class QuestionBankItem(Base):
    """项目级题库题目主表，独立于具体考试 questions。"""

    __tablename__ = "question_bank_items"
    __table_args__ = (UniqueConstraint("duplicate_key", name="uk_qb_item_duplicate_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(50), nullable=True)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(Enum("pending", "approved", "rejected"), nullable=False, default="pending")
    duplicate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class QuestionBankSource(Base):
    """项目级题目来源，一题可对应多个来源。"""

    __tablename__ = "question_bank_sources"
    __table_args__ = (UniqueConstraint("item_id", "paper_id", "question_no", name="uk_qb_source_item_paper_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paper_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
