from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import reveal_secret, settings
from app.models.user import User
from app.models.wechat import (
    WECHAT_BIND_PURPOSE_ACCOUNT,
    WECHAT_BIND_PURPOSE_GUARDIAN_INVITE,
    WECHAT_CHANNEL_ILINK_BOT,
    WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    WechatAccount,
    WechatBindSession,
    WechatGuardianStudentContext,
)
from app.core.auth import access_service
from app.features.wechat.guardian import get_guardian_push_time_config
from app.utils.security import hash_password


def _now() -> datetime:
    return datetime.utcnow()


def _new_bind_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "W" + "".join(secrets.choice(alphabet) for _ in range(6))


def _new_scene() -> str:
    return f"studybuddy_bind_{secrets.token_urlsafe(18)}"


def build_active_identity_key(channel: str, provider_account_id: str | None, openid: str) -> str:
    """生成数据库唯一的有效渠道身份键。"""
    raw = "\0".join((channel.strip(), (provider_account_id or "").strip(), openid.strip()))
    return hashlib.sha256(raw.encode()).hexdigest()


def create_bind_session(
    db: Session,
    user: User | None,
    *,
    channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    qr_value: str | None = None,
    provider_session_id: str | None = None,
    invited_by_user_id: int | None = None,
    purpose: str = WECHAT_BIND_PURPOSE_ACCOUNT,
) -> WechatBindSession:
    if purpose == WECHAT_BIND_PURPOSE_ACCOUNT and user is None:
        raise ValueError("绑定账号不存在")
    if purpose == WECHAT_BIND_PURPOSE_GUARDIAN_INVITE and (user is not None or invited_by_user_id is None):
        raise ValueError("家长邀请目标无效")
    if channel == WECHAT_CHANNEL_ILINK_BOT and qr_value is None and provider_session_id is None:
        response = httpx.post(
            f"{settings.WECHAT_BOT_SERVICE_URL.rstrip('/')}/v1/authorizations",
            headers={"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)},
            timeout=settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        authorization = response.json()
        qr_value = str(authorization["qr_value"])
        provider_session_id = str(authorization["session_id"])
    expires_at = _now() + timedelta(seconds=settings.WECHAT_BIND_EXPIRE_SECONDS)
    for _ in range(8):
        bind_code = _new_bind_code()
        if not db.query(WechatBindSession).filter(WechatBindSession.bind_code == bind_code).first():
            break
    else:
        raise RuntimeError("生成微信绑定码失败")
    scene = _new_scene()
    session = WechatBindSession(
        user_id=user.id if user else None,
        purpose=purpose,
        channel=channel,
        provider_session_id=provider_session_id,
        invited_by_user_id=invited_by_user_id,
        scene=scene,
        bind_code=bind_code,
        qr_value=qr_value if qr_value is not None else settings.WECHAT_OFFICIAL_ACCOUNT_QR_URL,
        status="pending",
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def create_guardian_invitation(
    db: Session,
    student: User,
    *,
    qr_value: str | None = None,
    provider_session_id: str | None = None,
) -> WechatBindSession:
    """为学生创建不要求家长预先注册的微信邀请。"""
    if student.role != "student":
        raise ValueError("只有学生可以邀请家长")
    return create_bind_session(
        db,
        None,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value=qr_value,
        provider_session_id=provider_session_id,
        invited_by_user_id=student.id,
        purpose=WECHAT_BIND_PURPOSE_GUARDIAN_INVITE,
    )


def list_known_ilink_provider_account_ids(db: Session) -> set[str]:
    """返回保留在历史绑定中的 Bot 身份，与当前活跃用户数无关。"""
    return {
        provider_account_id
        for (provider_account_id,) in db.query(WechatAccount.provider_account_id)
        .filter(
            WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatAccount.provider_account_id.isnot(None),
        )
        .distinct()
        .all()
        if provider_account_id
    }


def get_active_account(db: Session, user_id: int, *, channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT) -> WechatAccount | None:
    return (
        db.query(WechatAccount)
        .filter(
            WechatAccount.user_id == user_id,
            WechatAccount.channel == channel,
            WechatAccount.status == "active",
        )
        .order_by(WechatAccount.id.desc())
        .first()
    )


def create_parent_invitation_reply(db: Session, student: User) -> str:
    """为当前学生的已有家长生成三分钟微信绑定邀请。"""
    parents = access_service.list_bound_teachers(db, student.id)
    if not parents:
        return "当前没有已绑定家长"
    lines: list[str] = []
    for parent in parents:
        session = create_bind_session(
            db,
            parent,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            invited_by_user_id=student.id,
        )
        invitation_url = f"{settings.WECHAT_PARENT_INVITATION_URL}?" f"{urlencode({'token': session.scene})}"
        lines.append(f"{parent.display_name or parent.username}：{invitation_url}")
    return "\n".join(lines)


def get_parent_invitation(db: Session, scene: str) -> tuple[WechatBindSession, User, User] | None:
    """读取仍属于现有亲子关系的家长邀请。"""
    session = (
        db.query(WechatBindSession)
        .filter(
            WechatBindSession.scene == scene.strip(),
            WechatBindSession.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatBindSession.invited_by_user_id.isnot(None),
        )
        .first()
    )
    if not session or session.invited_by_user_id is None:
        return None
    parent = db.get(User, session.user_id)
    student = db.get(User, session.invited_by_user_id)
    if not parent or not student:
        return None
    if parent.role != "teacher" or student.role != "student":
        return None
    if not access_service.teacher_can_access_student(db, parent.id, student.id):
        return None
    if session.status == "pending" and session.expires_at <= _now():
        session.status = "expired"
        db.commit()
        db.refresh(session)
    elif session.status == "pending":
        session = get_bind_session(db, session.id, refresh_provider=True) or session
    return session, parent, student


def list_active_ilink_accounts(db: Session) -> list[WechatAccount]:
    """返回微服务重启后需要恢复的有效 iLink 账号。"""
    return (
        db.query(WechatAccount)
        .filter(
            WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatAccount.status == "active",
            WechatAccount.provider_account_id.isnot(None),
        )
        .all()
    )


def get_active_account_by_openid(
    db: Session,
    openid: str,
    *,
    channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    provider_account_id: str | None = None,
) -> WechatAccount | None:
    """按 openid 读取最新有效微信绑定。"""
    query = db.query(WechatAccount).filter(
        WechatAccount.openid == openid.strip(),
        WechatAccount.channel == channel,
        WechatAccount.status == "active",
    )
    if provider_account_id is not None:
        query = query.filter(WechatAccount.provider_account_id == provider_account_id.strip())
    return query.order_by(WechatAccount.id.desc()).first()


def get_bind_session(db: Session, session_id: int, *, refresh_provider: bool = False) -> WechatBindSession | None:
    session = db.get(WechatBindSession, session_id)
    if not session:
        return None
    if not refresh_provider:
        return session
    if session.channel != WECHAT_CHANNEL_ILINK_BOT or session.status != "pending":
        return session
    if not session.provider_session_id:
        return session
    response = httpx.get(
        f"{settings.WECHAT_BOT_SERVICE_URL.rstrip('/')}/v1/authorizations/{session.provider_session_id}",
        headers={"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)},
        timeout=settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    authorization = response.json()
    session.qr_value = str(authorization.get("qr_value") or session.qr_value)
    authorization_status = authorization.get("status")
    if authorization_status == "confirmed":
        session.provider_account_id = authorization.get("provider_account_id")
        session.wechat_openid = authorization.get("ilink_user_id")
    elif authorization_status in {"expired", "failed"}:
        session.status = "expired"
    db.commit()
    db.refresh(session)
    return session


def get_pending_bind_session_by_code(db: Session, bind_code: str) -> WechatBindSession | None:
    normalized_code = bind_code.strip().upper()
    if not normalized_code:
        return None
    return (
        db.query(WechatBindSession)
        .filter(
            WechatBindSession.bind_code == normalized_code,
            WechatBindSession.status == "pending",
        )
        .first()
    )


def complete_bind_by_code(
    db: Session,
    bind_code: str,
    openid: str,
    *,
    channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    provider_account_id: str | None = None,
) -> WechatBindSession:
    normalized_code = bind_code.strip().upper()
    normalized_openid = openid.strip()
    normalized_provider_account_id = (provider_account_id or "").strip()
    if not normalized_code or not normalized_openid:
        raise ValueError("绑定码或微信身份为空")

    session = db.query(WechatBindSession).filter(WechatBindSession.bind_code == normalized_code).first()
    if not session:
        raise ValueError("绑定码无效")
    if session.status == "bound":
        raise ValueError("绑定码已使用")
    if session.status != "pending":
        raise ValueError("绑定码不可用")
    if session.channel != channel:
        raise ValueError("绑定码渠道不匹配")
    if channel == WECHAT_CHANNEL_ILINK_BOT:
        # 扫码确认后的身份可能尚未由前端轮询回填，主动向 Bot 微服务刷新一次，
        # 避免“扫码后立即发码”因 provider_account_id 为空而误判身份不一致。
        if not session.provider_account_id and session.provider_session_id:
            session = get_bind_session(db, session.id, refresh_provider=True)
            if session.status != "pending":
                raise ValueError("绑定码已失效")
        if session.provider_account_id != normalized_provider_account_id:
            raise ValueError("微信学习助手身份不一致")
        if session.wechat_openid and session.wechat_openid != normalized_openid:
            raise ValueError("扫码微信身份不一致")
    if session.expires_at <= _now():
        session.status = "expired"
        db.commit()
        raise ValueError("绑定码已过期")

    if session.purpose == WECHAT_BIND_PURPOSE_GUARDIAN_INVITE:
        student = db.get(User, session.invited_by_user_id)
        if not student or student.role != "student":
            raise ValueError("邀请学生不存在")
        existing = get_active_account_by_openid(
            db,
            normalized_openid,
            channel=channel,
            provider_account_id=normalized_provider_account_id,
        )
        guardian = db.get(User, existing.user_id) if existing else None
        if guardian and guardian.role == "student":
            raise ValueError("学生微信身份不能绑定为家长")
        if guardian and guardian.role != "teacher":
            raise ValueError("微信身份角色冲突")

        if guardian is None:
            for _ in range(8):
                username = f"wechat_guardian_{secrets.token_urlsafe(12)}"
                if not db.query(User).filter(User.username == username).first():
                    break
            else:
                raise RuntimeError("生成家长内部账号失败")
            guardian = User(
                username=username,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="teacher",
                display_name="微信家长",
                web_login_enabled=False,
            )
            db.add(guardian)
            db.flush()

        now = _now()
        session.user_id = guardian.id
        session.status = "bound"
        session.wechat_openid = normalized_openid
        session.provider_account_id = normalized_provider_account_id
        session.bound_at = now
        if existing:
            existing.last_interacted_at = now
            existing.proactive_message_count = 0
            existing.proactive_message_window_started_at = now
            account = existing
        else:
            account = WechatAccount(
                user_id=guardian.id,
                channel=channel,
                provider_account_id=normalized_provider_account_id,
                openid=normalized_openid,
                guardian_onboarding_status="awaiting_push_time",
                guardian_default_push_time=get_guardian_push_time_config()[1],
                selected_student_id=student.id,
                active_identity_key=build_active_identity_key(channel, normalized_provider_account_id, normalized_openid),
                status="active",
                bound_at=now,
                last_interacted_at=now,
                proactive_message_count=0,
                proactive_message_window_started_at=now,
            )
            db.add(account)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError("微信已绑定其他账号") from exc
        access_service.bind_teacher_student(db, guardian.id, student.id)
        push_time = account.guardian_default_push_time or get_guardian_push_time_config()[1]
        if account.guardian_default_push_time is None:
            account.guardian_default_push_time = push_time
        if account.selected_student_id is None:
            account.selected_student_id = student.id
        context = (
            db.query(WechatGuardianStudentContext)
            .filter(
                WechatGuardianStudentContext.account_id == account.id,
                WechatGuardianStudentContext.student_id == student.id,
            )
            .first()
        )
        is_new_context = context is None
        if context:
            context.status = "active"
            context.paused = False
            context.push_time = push_time
        else:
            db.add(
                WechatGuardianStudentContext(
                    account_id=account.id,
                    student_id=student.id,
                    push_time=push_time,
                )
            )
        db.flush()
        if is_new_context:
            active_context_count = (
                db.query(WechatGuardianStudentContext.id)
                .filter(
                    WechatGuardianStudentContext.account_id == account.id,
                    WechatGuardianStudentContext.status == "active",
                )
                .count()
            )
            if active_context_count > 1:
                account.selected_student_id = None
        db.commit()
        db.refresh(session)
        return session

    user = db.get(User, session.user_id)
    if not user:
        raise ValueError("绑定账号不存在")
    if user.role == "teacher":
        if session.invited_by_user_id and not access_service.teacher_can_access_student(db, user.id, session.invited_by_user_id):
            raise ValueError("家长账号尚未绑定该学生")
        if not access_service.list_accessible_students(db, user.id):
            raise ValueError("家长账号尚未绑定学生")

    existing = (
        db.query(WechatAccount)
        .filter(
            WechatAccount.openid == normalized_openid,
            WechatAccount.channel == channel,
            WechatAccount.status == "active",
        )
        .first()
    )
    if existing and existing.user_id != session.user_id:
        raise ValueError("微信已绑定其他账号")
    if existing and existing.user_id == session.user_id:
        session.status = "bound"
        session.wechat_openid = normalized_openid
        session.provider_account_id = provider_account_id
        session.bound_at = _now()
        existing.provider_account_id = provider_account_id
        existing.active_identity_key = build_active_identity_key(channel, provider_account_id, normalized_openid)
        existing.last_interacted_at = session.bound_at
        existing.proactive_message_count = 0
        existing.proactive_message_window_started_at = session.bound_at
        db.commit()
        db.refresh(session)
        return session

    now = _now()
    account = WechatAccount(
        user_id=session.user_id,
        channel=channel,
        provider_account_id=provider_account_id,
        openid=normalized_openid,
        active_identity_key=build_active_identity_key(channel, provider_account_id, normalized_openid),
        status="active",
        bound_at=now,
        last_interacted_at=now,
        proactive_message_count=0,
        proactive_message_window_started_at=now,
    )
    session.status = "bound"
    session.wechat_openid = normalized_openid
    session.provider_account_id = provider_account_id
    session.bound_at = now
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("微信已绑定其他账号") from exc
    db.refresh(session)
    return session


def unbind_account(db: Session, user: User, *, channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT) -> None:
    accounts = (
        db.query(WechatAccount)
        .filter(
            WechatAccount.user_id == user.id,
            WechatAccount.channel == channel,
            WechatAccount.status == "active",
        )
        .all()
    )
    if not accounts:
        return
    now = _now()
    for account in accounts:
        account.status = "unbound"
        account.active_identity_key = None
        account.unbound_at = now
        account.revocation_pending = channel == WECHAT_CHANNEL_ILINK_BOT
    db.commit()


def has_pending_ilink_revocation(db: Session, provider_account_id: str, ilink_user_id: str) -> bool:
    return (
        db.query(WechatAccount.id)
        .filter(
            WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatAccount.provider_account_id == provider_account_id.strip(),
            WechatAccount.openid == ilink_user_id.strip(),
            WechatAccount.status == "unbound",
            WechatAccount.revocation_pending.is_(True),
        )
        .first()
        is not None
    )


def clear_ilink_revocation_pending(db: Session, provider_account_id: str, ilink_user_id: str) -> None:
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
        WechatAccount.provider_account_id == provider_account_id,
        WechatAccount.openid == ilink_user_id,
        WechatAccount.status == "unbound",
        WechatAccount.revocation_pending.is_(True),
    ).update({WechatAccount.revocation_pending: False}, synchronize_session=False)
    db.commit()


def revoke_ilink_user(provider_account_id: str, ilink_user_id: str) -> None:
    """通知微信 Bot 微服务移除指定用户白名单。"""
    response = httpx.delete(
        f"{settings.WECHAT_BOT_SERVICE_URL.rstrip('/')}/v1/accounts/"
        f"{quote(provider_account_id, safe='')}/users/{quote(ilink_user_id, safe='')}",
        headers={"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)},
        timeout=settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def record_interaction(
    db: Session,
    openid: str,
    *,
    channel: str = WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    provider_account_id: str | None = None,
) -> WechatAccount | None:
    """记录公众号用户最近一次主动互动。"""
    account = get_active_account_by_openid(db, openid, channel=channel, provider_account_id=provider_account_id)
    if account:
        interacted_at = _now()
        account.last_interacted_at = interacted_at
        if channel == WECHAT_CHANNEL_ILINK_BOT:
            account.proactive_message_count = 0
            account.proactive_message_window_started_at = interacted_at
        db.commit()
    return account
