"""学生主动向家长报进度：把当日 AI 学习摘要推送给绑定的家长微信。

边界：只推送当日 daily_record.summary_text，不记录/判断学习时长。
时长可靠性由 daily_summary_service 保证；本模块只负责发送。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.models.wechat import WECHAT_CHANNEL_ILINK_BOT
from app.features.growth import daily_record_service, daily_summary_service
from app.features.wechat import guardian, messaging

logger = logging.getLogger(__name__)


def send_student_progress_to_guardians(
    db: Session,
    student: User,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """学生主动把当日学习摘要发给绑定的家长微信。

    返回 {"sent": int, "failed": int}。
    - 当日无摘要 -> ValueError（接口层转 400）
    - 未绑定家长 -> ValueError（接口层转 400）
    - 全部发送失败 -> RuntimeError（接口层转 500）
    """
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    local_now = now or datetime.now(zone)
    local_now = local_now.astimezone(zone) if local_now.tzinfo else local_now.replace(tzinfo=zone)
    today = local_now.date()

    record = daily_record_service.get_by_date(db, student_id=student.id, record_date=today)
    if record is None or not daily_summary_service.has_learning_facts(record.facts_snapshot or {}):
        raise ValueError("今天还没有学习记录，学完再来报进度")

    contexts = guardian.list_guardian_contexts_for_student(db, student)
    if not contexts:
        raise ValueError("还没绑定家长微信，先去个人中心绑定后再报进度")

    content = record.summary_text.strip()
    sent = 0
    failed = 0
    for _context, account, _guardian_user in contexts:
        try:
            if account.channel == WECHAT_CHANNEL_ILINK_BOT:
                if not account.provider_account_id:
                    failed += 1
                    continue
                messaging.send_ilink_text(account.provider_account_id, account.openid, content)
            else:
                messaging.send_customer_text(account.openid, content)
            sent += 1
        except Exception:
            logger.warning("report progress send failed: account_id=%s", account.id, exc_info=True)
            failed += 1
    if sent == 0:
        raise RuntimeError("发送失败，请稍后重试")
    return {"sent": sent, "failed": failed}
