"""检查家长每日推送健康度：有活跃家长绑定但当天没产出成长摘要则告警。

由 cron 在每晚推送窗口后调用（见 setup_daily_coach_cron.sh）。
告警方式：
  - 始终 print 一条 status JSON（cron 重定向到 logs/check_parent_reminder_health.log）
  - 异常时 logger.error
  - 若设置了环境变量 ALERT_ILINK_PROVIDER + ALERT_ILINK_USER_ID，额外通过 iLink 机器人发一条微信告警
"""

import json
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.features.wechat import messaging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("parent_reminder_health")


def main() -> int:
    """返回 0=正常，1=告警。"""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    today = datetime.now(zone).date()
    ts = datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S %Z")
    db = SessionLocal()
    try:
        active_contexts = db.execute(
            text("select count(*) from wechat_guardian_student_contexts where status='active' and paused=0")
        ).scalar() or 0
        today_sent = db.execute(
            text(
                "select count(*) from notifications "
                "where source_type='growth_summary' and date(created_at)=:d"
            ),
            {"d": today},
        ).scalar() or 0
    finally:
        db.close()
    status = "ok" if (active_contexts == 0 or today_sent > 0) else "alert"
    print(
        json.dumps(
            {
                "ts": ts,
                "date": str(today),
                "active_contexts": active_contexts,
                "today_growth_sent": today_sent,
                "status": status,
            },
            ensure_ascii=False,
        )
    )
    if status == "alert":
        msg = (
            f"⚠️ 家长推送告警：{today} 有 {active_contexts} 个活跃家长绑定，"
            f"但当天 0 条成长摘要推送。请检查 logs/dispatch_parent.log。"
        )
        logger.error(msg)
        provider = os.environ.get("ALERT_ILINK_PROVIDER")
        user_id = os.environ.get("ALERT_ILINK_USER_ID")
        if provider and user_id:
            try:
                messaging.send_ilink_text(provider, user_id, msg)
                logger.info("告警已通过 iLink 发送: %s...", user_id[:6])
            except Exception:
                logger.warning("告警微信发送失败", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
