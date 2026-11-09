"""笔记模型：学习记录层（concept 概念卡已废弃，统一 study_record）。

笔记分类用 category 字段（学科下的细分，如 词汇/语法/阅读），由 agent 保存时判断。
盲区层不存表，从 error_book 聚合（见 note_service.get_blind_spots）。
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    # 笔记类型：study_record=学习记录（concept 概念卡已废弃，不再生成）
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="study_record")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(20), nullable=False, default="其他")
    # 学科下的一级细分分类，由 agent 判断：英语→词汇/语法/阅读，数学→函数/几何/代数，
    # 语文→古诗文/现代文/作文，课外→兴趣/拓展。自由文本，给 agent 灵活度
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 笔记正文（Markdown，AI 整理 + 弟弟确认）
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 知识点标签，如 ["过去时","不规则动词"]
    knowledge_tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    # 来源：错题讲解 / 视频学习 / 做题 / 素材整理 / 其他
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="其他")
    # 溯源：关联错题id / 视频BV号 / 试卷id，JSON
    source_ref: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    # draft=草稿 / confirmed=弟弟已确认
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # naive UTC：aggregate_daily_facts 用 naive UTC 窗口比较 created_at；server_default=func.now()
    # = MySQL NOW()，CST session 下写本地会落不进当日窗口。对齐 completed_at/recognized_at 口径。
    # microsecond=0 避免 DATETIME 秒级四舍五入进位越过 utc_end(详见 completed_at 注释)。
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
