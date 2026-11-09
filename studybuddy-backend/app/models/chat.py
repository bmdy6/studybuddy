"""对话会话与消息模型（P2 agent 化）。

M1 只建对话主链路所需的两张表；兴趣/反馈/推荐/属性四表随 F3-F5 在 M5 再建。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatSession(Base):
    """一次 agent 对话会话（关联发起人 + 学生）。"""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_at_create: Mapped[str] = mapped_column(Enum("teacher", "student"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="新对话")
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_summary_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 学生长期主会话标识：只有学生自己的主会话写入学生 id，辅导者会话和其他学生旧会话保持 NULL。
    # 复合唯一 (primary_student_id, mode)：每个模式（study/hobby）各自一个主会话，互不串上下文。
    primary_student_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 模式：study=学习(默认) / hobby=兴趣爱好（同一账号切换，会话历史按模式隔离）
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="study", server_default="study")
    # U-042 任务会话：main=计划协商主会话，task=单个计划项的执行会话
    session_type: Mapped[str] = mapped_column(String(16), nullable=False, default="main")
    plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    plan_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # context_version：DB 列存在（DDL 022/ensure 创建）但当前未实现「计划改后刷新 task 上下文」逻辑，
    # ORM 不映射，勿读写。真要启用需在 update_study_plan 后 bump 并让 run_agent_turn 检测重建 task_context。
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# 复合唯一：同一学生同一模式一个主会话（MySQL 5.7 UNIQUE 允许多 NULL，非主会话不受限）
Index(
    "uk_chat_sessions_primary_mode",
    ChatSession.primary_student_id,
    ChatSession.mode,
    unique=True,
)


class ChatMessage(Base):
    """对话消息（user / assistant / tool_result 三种角色）。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Enum("user", "assistant", "tool"), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # assistant 的工具调用请求（name/input）；tool 的结果摘要；纯文本消息为 NULL
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    tool_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
