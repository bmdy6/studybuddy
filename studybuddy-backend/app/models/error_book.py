from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ErrorBook(Base):
    __tablename__ = "error_book"
    __table_args__ = (UniqueConstraint("student_id", "question_id", name="uk_student_question"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    exam_record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exam_records.id", ondelete="CASCADE"), nullable=False)
    knowledge_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)  # 从 question 冗余，加速聚合
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_wrong_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # tag_array 为 MySQL 生成虚拟列，ORM 不写入只读取，故不在此声明写入逻辑
