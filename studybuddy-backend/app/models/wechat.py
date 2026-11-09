from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

WECHAT_CHANNEL_OFFICIAL_ACCOUNT = "official_account"
WECHAT_CHANNEL_ILINK_BOT = "ilink_bot"
WECHAT_BIND_PURPOSE_ACCOUNT = "account_bind"
WECHAT_BIND_PURPOSE_GUARDIAN_INVITE = "guardian_invite"


class WechatBindSession(Base):
    __tablename__ = "wechat_bind_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(
        Enum(WECHAT_BIND_PURPOSE_ACCOUNT, WECHAT_BIND_PURPOSE_GUARDIAN_INVITE),
        nullable=False,
        default=WECHAT_BIND_PURPOSE_ACCOUNT,
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WECHAT_CHANNEL_OFFICIAL_ACCOUNT, index=True
    )
    provider_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    invited_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True, index=True
    )
    scene: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    bind_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    qr_value: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "bound", "expired", "cancelled"), nullable=False, default="pending"
    )
    wechat_openid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WechatGuardianStudentContext(Base):
    __tablename__ = "wechat_guardian_student_contexts"
    __table_args__ = (UniqueConstraint("account_id", "student_id", name="uq_wechat_guardian_student"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wechat_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_session_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True)
    push_time: Mapped[str] = mapped_column(String(5), nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Enum("active", "unbound"), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WechatAccount(Base):
    __tablename__ = "wechat_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    chat_session_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WECHAT_CHANNEL_OFFICIAL_ACCOUNT, index=True
    )
    provider_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    openid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    guardian_onboarding_status: Mapped[str] = mapped_column(
        Enum("awaiting_push_time", "completed"), nullable=False, default="completed"
    )
    guardian_default_push_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    selected_student_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    active_identity_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(Enum("active", "unbound"), nullable=False, default="active")
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    login_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    login_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    login_token_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_interacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminder_times: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    last_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reminder_claimed_minute: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proactive_message_count: Mapped[int] = mapped_column(nullable=False, default=0)
    proactive_message_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    revocation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
