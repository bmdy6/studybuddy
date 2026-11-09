from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExamAssignment(Base):
    __tablename__ = "exam_assignments"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_exam_assignment_exam_student"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 故意不建 FK（仿 chat_sessions.plan_id/plan_item_id 模式）：删计划项时由应用层清理 assignment，
    # 避免 ON DELETE SET NULL 在已存孤儿数据上加约束失败。DDL 024 与 ensure 脚本也无 FK，保持一致。
    plan_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="自练卷关联的学习计划项（纯自练为空）")
    status: Mapped[str] = mapped_column(
        Enum("assigned", "started", "submitted", "cancelled"),
        nullable=False,
        default="assigned",
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
