from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum("teacher", "student"), nullable=False)
    # 模式：study=学习(默认) / hobby=兴趣爱好（同账号切换，全量复用）
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="study", server_default="study"
    )
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 头像：存 URL 或 null（前端用默认头像兜底）。个人中心可改（UX P0-1）
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    web_login_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
