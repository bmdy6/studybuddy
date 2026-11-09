from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.notification import Notification
from app.models.user import User
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WechatAccount,
    WechatGuardianStudentContext,
)
from app.core.auth import access_service
from app.core.infra import notification_service
from . import daily_record_service as daily_learning_record_service

from . import summary
from .facts import GrowthPeriod, guardian_summary_facts_from_records

logger = logging.getLogger(__name__)


def _report_key(period: GrowthPeriod, local_now: datetime) -> str:
    if period == "daily":
        return local_now.date().isoformat()
    iso_year, iso_week, _ = local_now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def dispatch_due_growth_summaries(
    db: Session,
    *,
    now: datetime | None = None,
    send_ilink: Callable[[str, str, str], str],
) -> dict[str, int]:
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now or datetime.now(zone)
    local_now = local_now.astimezone(zone)
    utc_now = local_now.astimezone(timezone.utc).replace(tzinfo=None)
    current_time = local_now.strftime("%H:%M")
    current_minute = local_now.strftime("%Y-%m-%d %H:%M")
    cutoff = utc_now - timedelta(hours=settings.WECHAT_CUSTOMER_MESSAGE_WINDOW_HOURS)
    rows = (
        db.query(WechatGuardianStudentContext, WechatAccount, User)
        .join(WechatAccount, WechatAccount.id == WechatGuardianStudentContext.account_id)
        .join(User, User.id == WechatGuardianStudentContext.student_id)
        .filter(
            WechatGuardianStudentContext.status == "active",
            WechatGuardianStudentContext.paused.is_(False),
            WechatGuardianStudentContext.push_time == current_time,
            WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatAccount.status == "active",
            User.role == "student",
        )
        .order_by(WechatAccount.id.asc(), WechatGuardianStudentContext.id.asc())
        .all()
    )
    grouped: dict[int, list[tuple[WechatGuardianStudentContext, WechatAccount, User]]] = defaultdict(list)
    for row in rows:
        grouped[row[1].id].append(row)

    result = {"sent": 0, "paused": 0, "failed": 0}
    period: GrowthPeriod = "weekly" if local_now.weekday() == 6 else "daily"
    period_key = _report_key(period, local_now)
    if not grouped:
        logger.info(
            "growth dispatch: current_time=%s period=%s 无到期家长推送项 (rows=0)",
            current_time,
            period,
        )
    for account_rows in grouped.values():
        account = account_rows[0][1]
        if not account.last_interacted_at or account.last_interacted_at < cutoff:
            logger.info(
                "growth dispatch: account_id=%s outcome=paused reason=window_closed",
                account.id,
            )
            result["paused"] += 1
            continue
        if account.proactive_message_count >= settings.WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT or not account.provider_account_id:
            logger.info(
                "growth dispatch: account_id=%s outcome=paused reason=quota_or_no_provider count=%s",
                account.id,
                account.proactive_message_count,
            )
            result["paused"] += 1
            continue
        sent_at_current_minute = False
        if account.last_reminder_sent_at:
            sent_at = account.last_reminder_sent_at.replace(tzinfo=timezone.utc).astimezone(zone)
            sent_at_current_minute = sent_at.strftime("%Y-%m-%d %H:%M") == current_minute
        if sent_at_current_minute:
            # A previous partial batch may have sent one child's section while
            # another child failed before its Notification was created. Retry
            # only while a bound, accessible child is still missing its period
            # notification; otherwise this invocation would duplicate a send.
            all_notified = True
            for _context, _account, student in account_rows:
                if not access_service.teacher_can_access_student(db, account.user_id, student.id):
                    continue
                dedupe_key = f"growth:{period}:{period_key}"
                if not (
                    db.query(Notification.id)
                    .filter(
                        Notification.recipient_id == account.user_id,
                        Notification.student_id == student.id,
                        Notification.source_type == "growth_summary",
                        Notification.source_id == student.id,
                        Notification.dedupe_key == dedupe_key,
                    )
                    .first()
                ):
                    all_notified = False
                    break
            if all_notified:
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
            continue

        existing_period_students: set[int] = set()
        missing_period_notification = False
        for _context, _account, student in account_rows:
            if not access_service.teacher_can_access_student(db, account.user_id, student.id):
                continue
            dedupe_key = f"growth:{period}:{period_key}"
            existing = (
                db.query(Notification.id)
                .filter(
                    Notification.recipient_id == account.user_id,
                    Notification.student_id == student.id,
                    Notification.source_type == "growth_summary",
                    Notification.source_id == student.id,
                    Notification.dedupe_key == dedupe_key,
                )
                .first()
            )
            if existing:
                existing_period_students.add(student.id)
            else:
                missing_period_notification = True
        retrying_partial_batch = bool(existing_period_students) and missing_period_notification
        sections: list[str] = []
        had_generation_failure = False
        for _context, _account, student in account_rows:
            if not access_service.teacher_can_access_student(db, account.user_id, student.id):
                continue
            dedupe_key = f"growth:{period}:{period_key}"
            notification = (
                db.query(Notification)
                .filter(
                    Notification.recipient_id == account.user_id,
                    Notification.student_id == student.id,
                    Notification.source_type == "growth_summary",
                    Notification.source_id == student.id,
                    Notification.dedupe_key == dedupe_key,
                )
                .first()
            )
            notification_created = False
            if not notification:
                try:
                    # Refresh the shared daily record first. The push path then
                    # reads only persisted daily facts; it must not maintain a
                    # second evidence-query implementation.
                    asyncio.run(
                        daily_learning_record_service.refresh(
                            db,
                            student.id,
                            local_now.date(),
                            now=local_now,
                        )
                    )
                    if period == "daily":
                        daily_record = daily_learning_record_service.get_by_date(
                            db,
                            student_id=student.id,
                            record_date=local_now.date(),
                        )
                        records = [daily_record] if daily_record else []
                    else:
                        week_start = local_now.date() - timedelta(days=local_now.weekday())
                        records = daily_learning_record_service.list_by_range(
                            db,
                            student_id=student.id,
                            start_date=week_start,
                            end_date=local_now.date(),
                        )
                    period_start = datetime.combine(
                        local_now.date() if period == "daily" else local_now.date() - timedelta(days=local_now.weekday()),
                        time.min,
                        tzinfo=zone,
                    )
                    facts = guardian_summary_facts_from_records(
                        [record for record in records if record is not None],
                        period=period,
                        period_start=period_start,
                        period_end=local_now,
                    )
                    content = summary.generate_guardian_positive_summary(facts)
                except Exception:
                    logger.warning(
                        "家长成长摘要生成失败: account_id=%s student_id=%s",
                        account.id,
                        student.id,
                        exc_info=True,
                    )
                    # The account claim was committed before per-student
                    # generation. Roll back a failed refresh/session, but keep
                    # the claim while other children in this account are
                    # still being assembled so a competing dispatcher cannot
                    # send a duplicate partial message.
                    db.rollback()
                    result["failed"] += 1
                    had_generation_failure = True
                    continue
                item, notification_created = notification_service.create_notification_once(
                    db,
                    recipient_id=account.user_id,
                    student_id=student.id,
                    title="本周成长总结" if period == "weekly" else "今日成长摘要",
                    content=content,
                    notification_type=f"{period}_growth_summary",
                    source_type="growth_summary",
                    source_id=student.id,
                    dedupe_key=dedupe_key,
                )
                if item:
                    notification = db.get(Notification, item.id)
            if notification and (
                notification_created or (not sent_at_current_minute and not retrying_partial_batch)
            ):
                sections.append(f"{student.display_name or student.username}\n{notification.content}")
        if not sections:
            logger.info(
                "growth dispatch: account_id=%s outcome=skipped reason=no_sections",
                account.id,
            )
            account.last_reminder_claimed_minute = None
            db.commit()
            continue
        try:
            provider_status = send_ilink(
                account.provider_account_id,
                account.openid,
                "\n\n".join(sections),
            )
        except Exception:
            logger.info(
                "growth dispatch: account_id=%s outcome=failed reason=send_exception",
                account.id,
                exc_info=True,
            )
            account.last_reminder_claimed_minute = None
            db.commit()
            result["failed"] += 1
            continue
        if provider_status in {"window_closed", "session_expired", "not_allowed"}:
            logger.info(
                "growth dispatch: account_id=%s outcome=paused reason=provider_status=%s",
                account.id,
                provider_status,
            )
            account.last_reminder_claimed_minute = None
            db.commit()
            result["paused"] += 1
            continue
        if provider_status != "success":
            logger.info(
                "growth dispatch: account_id=%s outcome=failed reason=provider_status=%s",
                account.id,
                provider_status,
            )
            account.last_reminder_claimed_minute = None
            db.commit()
            result["failed"] += 1
            continue
        account.proactive_message_count += 1
        if had_generation_failure:
            account.last_reminder_claimed_minute = None
        else:
            account.last_reminder_sent_at = utc_now
        db.commit()
        logger.info(
            "growth dispatch: account_id=%s outcome=sent student_ids=%s period=%s",
            account.id,
            [s.id for _, _, s in account_rows],
            period,
        )
        result["sent"] += 1
    return result
