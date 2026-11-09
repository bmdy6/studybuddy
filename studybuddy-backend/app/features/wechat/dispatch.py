from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    WechatAccount,
    WechatGuardianStudentContext,
)
from app.features.wechat.guardian import build_parent_daily_summary
from app.features.wechat.messaging import send_customer_text, send_ilink_text

logger = logging.getLogger(__name__)


def dispatch_parent_reminders(
    db: Session,
    now: datetime | None = None,
    send_text: Callable[[str, str], None] = send_customer_text,
    send_ilink: Callable[[str, str, str], str] = send_ilink_text,
) -> dict[str, int]:
    """派发到点且仍在微信互动窗口内的家长提醒。"""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now or datetime.now(zone)
    utc_now = local_now.astimezone(timezone.utc).replace(tzinfo=None)
    current_time = local_now.strftime("%H:%M")
    current_minute = local_now.strftime("%Y-%m-%d %H:%M")
    cutoff = utc_now - timedelta(hours=settings.WECHAT_CUSTOMER_MESSAGE_WINDOW_HOURS)
    accounts = (
        db.query(WechatAccount)
        .join(User, User.id == WechatAccount.user_id)
        .filter(
            WechatAccount.status == "active",
            WechatAccount.channel.in_([WECHAT_CHANNEL_OFFICIAL_ACCOUNT, WECHAT_CHANNEL_ILINK_BOT]),
            WechatAccount.reminder_times.isnot(None),
            User.role == "teacher",
        )
        .all()
    )
    result = {"sent": 0, "paused": 0, "failed": 0}
    for account in accounts:
        if account.channel == WECHAT_CHANNEL_ILINK_BOT:
            has_guardian_context = (
                db.query(WechatGuardianStudentContext.id)
                .filter(
                    WechatGuardianStudentContext.account_id == account.id,
                    WechatGuardianStudentContext.status == "active",
                )
                .first()
            )
            if has_guardian_context:
                continue
        if current_time not in (account.reminder_times or []):
            continue
        if not account.last_interacted_at or account.last_interacted_at < cutoff:
            logger.info(
                "legacy dispatch: account_id=%s channel=%s outcome=paused reason=window_closed",
                account.id,
                account.channel,
            )
            result["paused"] += 1
            continue
        if account.last_reminder_sent_at:
            sent_at = account.last_reminder_sent_at.replace(tzinfo=timezone.utc).astimezone(zone)
            if sent_at.strftime("%Y-%m-%d %H:%M") == local_now.strftime("%Y-%m-%d %H:%M"):
                logger.info(
                    "legacy dispatch: account_id=%s channel=%s outcome=skipped reason=already_sent_this_minute",
                    account.id,
                    account.channel,
                )
                continue
        if account.channel == WECHAT_CHANNEL_ILINK_BOT:
            quota_exhausted = account.proactive_message_count >= (settings.WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT)
            if quota_exhausted or not account.provider_account_id:
                logger.info(
                    "legacy dispatch: account_id=%s outcome=paused reason=quota_or_no_provider count=%s",
                    account.id,
                    account.proactive_message_count,
                )
                result["paused"] += 1
                continue
        claimed = (
            db.query(WechatAccount)
            .filter(
                WechatAccount.id == account.id,
                or_(
                    WechatAccount.last_reminder_claimed_minute.is_(None),
                    WechatAccount.last_reminder_claimed_minute != current_minute,
                ),
            )
            .update(
                {WechatAccount.last_reminder_claimed_minute: current_minute},
                synchronize_session=False,
            )
        )
        db.commit()
        if not claimed:
            logger.info(
                "legacy dispatch: account_id=%s outcome=skipped reason=already_claimed_this_minute",
                account.id,
            )
            continue
        content = build_parent_daily_summary(db, account.user_id)
        if account.channel == WECHAT_CHANNEL_ILINK_BOT:
            try:
                provider_status = send_ilink(account.provider_account_id, account.openid, content)
            except Exception:
                logger.info(
                    "legacy dispatch: account_id=%s outcome=failed reason=send_exception",
                    account.id,
                    exc_info=True,
                )
                result["failed"] += 1
                continue
            if provider_status in {"window_closed", "session_expired", "not_allowed"}:
                logger.info(
                    "legacy dispatch: account_id=%s outcome=paused reason=provider_status=%s",
                    account.id,
                    provider_status,
                )
                result["paused"] += 1
                continue
            if provider_status != "success":
                logger.info(
                    "legacy dispatch: account_id=%s outcome=failed reason=provider_status=%s",
                    account.id,
                    provider_status,
                )
                result["failed"] += 1
                continue
            account.proactive_message_count += 1
            account.last_reminder_sent_at = utc_now
            db.commit()
            logger.info(
                "legacy dispatch: account_id=%s channel=ilink_bot outcome=sent",
                account.id,
            )
            result["sent"] += 1
            continue
        try:
            send_text(account.openid, content)
        except Exception:
            logger.info(
                "legacy dispatch: account_id=%s channel=official_account outcome=failed reason=send_exception",
                account.id,
                exc_info=True,
            )
            result["failed"] += 1
            continue
        account.last_reminder_sent_at = utc_now
        db.commit()
        logger.info(
            "legacy dispatch: account_id=%s channel=official_account outcome=sent",
            account.id,
        )
        result["sent"] += 1
    return result
