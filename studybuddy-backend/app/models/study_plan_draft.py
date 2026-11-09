"""学习计划草案模型。

计划草案是 AI 生成、学生待确认的计划草稿。学生点卡片"确认并创建"后，
草案转为 created 状态并记录 created_plan_id，正式计划用 draft_data 原子创建。
靠服务端 draft_id/revision/expires_at 做硬状态，不再靠聊天关键词猜确认。
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StudyPlanDraft(Base):
    __tablename__ = "study_plan_draft"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # 草案内容：{title, items, focus, planned_date}
    draft_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # 乐观锁版本号，草案修改递增
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # pending=待确认 / created=已创建 / superseded=被新草案替代
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 创建成功后记录的 plan_id，幂等用（重复确认返回同一个）
    created_plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # naive UTC，对齐 note.py 口径（aggregate_daily_facts 用 naive UTC 窗口比较）
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
