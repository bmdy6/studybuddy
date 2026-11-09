from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chat import ChatSession
from app.models.user import User
from app.models.wechat import WECHAT_CHANNEL_ILINK_BOT, WechatAccount, WechatGuardianStudentContext
from app.core.auth import access_service
from app.features.chat import agent, sessions
from app.features.growth import guardian_today
from app.features.wechat.guardian import _is_guardian_today_learning_query, get_or_create_guardian_chat_session
from app.features.wechat.messaging import send_ilink_text

logger = logging.getLogger(__name__)
_student_agent_locks: dict[int, asyncio.Lock] = {}
_guardian_agent_locks: dict[int, asyncio.Lock] = {}


def get_or_create_chat_session(db: Session, account: WechatAccount, user: User) -> ChatSession:
    """返回该微信身份的固定学习助手会话。

    模式隔离：已绑定会话 mode 必须与当前 user.mode 一致才复用；
    不一致（web 端切了模式）时按当前模式新建，微信侧跟随用户当前模式。
    """
    session = db.get(ChatSession, account.chat_session_id) if account.chat_session_id else None
    if session and session.user_id == user.id and getattr(session, "mode", "study") == user.mode:
        return session

    session = sessions.create_session(db, user, user.id)
    session.title = "微信学习助手"
    account.chat_session_id = session.id
    db.commit()
    db.refresh(session)
    return session


async def process_guardian_agent_message(account_id: int, student_id: int, content: str) -> None:
    lock = _guardian_agent_locks.setdefault(account_id, asyncio.Lock())
    provider_account_id = ""
    ilink_user_id = ""
    async with lock:
        try:
            with SessionLocal() as db:
                account = db.get(WechatAccount, account_id)
                guardian = db.get(User, account.user_id) if account else None
                context = (
                    db.query(WechatGuardianStudentContext)
                    .filter(
                        WechatGuardianStudentContext.account_id == account_id,
                        WechatGuardianStudentContext.student_id == student_id,
                        WechatGuardianStudentContext.status == "active",
                    )
                    .first()
                    if account
                    else None
                )
                binding_invalid = (
                    not account
                    or account.status != "active"
                    or account.channel != WECHAT_CHANNEL_ILINK_BOT
                    or not account.provider_account_id
                    or not guardian
                    or guardian.role != "teacher"
                    or not context
                )
                if not binding_invalid and not access_service.teacher_can_access_student(db, guardian.id, student_id):
                    binding_invalid = True
                if binding_invalid:
                    raise ValueError("微信家长绑定已失效")
                provider_account_id = account.provider_account_id or ""
                ilink_user_id = account.openid
                if _is_guardian_today_learning_query(content):
                    reply = guardian_today.build_guardian_today_learning_summary(db, student_id)
                else:
                    session = get_or_create_guardian_chat_session(db, context, guardian)
                    reply = await agent.run_agent_turn(
                        db,
                        session,
                        guardian,
                        content,
                        auto_title_session=False,
                        business_actor="channel_guardian",
                    )
                if not reply.strip():
                    raise RuntimeError("Agent 未返回文本")
            status = await asyncio.to_thread(send_ilink_text, provider_account_id, ilink_user_id, reply)
            if status != "success":
                raise RuntimeError(f"微信最终回复发送失败: {status}")
        except Exception:
            logger.warning("微信家长 Agent 消息处理失败", exc_info=True)
            if provider_account_id and ilink_user_id:
                await asyncio.to_thread(
                    send_ilink_text,
                    provider_account_id,
                    ilink_user_id,
                    "这次没有处理成功，请再发一次。",
                )


async def process_student_agent_message(account_id: int, content: str) -> None:
    """串行处理一个微信学生的 Agent 消息并主动回复。"""
    lock = _student_agent_locks.setdefault(account_id, asyncio.Lock())
    provider_account_id = ""
    ilink_user_id = ""
    async with lock:
        try:
            with SessionLocal() as db:
                account = db.get(WechatAccount, account_id)
                if not account:
                    raise ValueError("微信绑定不存在")
                provider_account_id = account.provider_account_id or ""
                ilink_user_id = account.openid
                user = db.get(User, account.user_id)
                binding_invalid = account.status != "active" or (account.channel != WECHAT_CHANNEL_ILINK_BOT)
                binding_invalid = binding_invalid or not provider_account_id or not user
                if user and user.role != "student":
                    binding_invalid = True
                if binding_invalid:
                    raise ValueError("微信学生绑定已失效")
                session = get_or_create_chat_session(db, account, user)
                reply = await agent.run_agent_turn(
                    db,
                    session,
                    user,
                    content,
                    auto_title_session=False,
                )
                if not reply.strip():
                    raise RuntimeError("Agent 未返回文本")

            status = await asyncio.to_thread(
                send_ilink_text,
                provider_account_id,
                ilink_user_id,
                reply,
            )
            if status != "success":
                raise RuntimeError(f"微信最终回复发送失败: {status}")
        except Exception:
            logger.warning("微信学生 Agent 消息处理失败", exc_info=True)
            if provider_account_id and ilink_user_id:
                try:
                    await asyncio.to_thread(
                        send_ilink_text,
                        provider_account_id,
                        ilink_user_id,
                        "这次没有处理成功，请再发一次。",
                    )
                except Exception:
                    logger.warning("微信学生 Agent 失败回复发送失败", exc_info=True)
