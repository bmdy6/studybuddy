"""派发微信公众号家长学习提醒。"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.database import SessionLocal
from app.features.wechat import dispatch as wechat_dispatch, messaging
from app.features.growth import dispatch

# basicConfig 让 service 层的 logger.info 输出到 stderr，cron 的 2>&1 会一并落进日志，
# 这样每跳每条都能按时间定位到「哪个家长、发了 / 为啥没发」。
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    """执行一次到点提醒派发并输出带时间戳的脱敏计数。"""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    ts = datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S %Z")
    with SessionLocal() as db:
        legacy = wechat_dispatch.dispatch_parent_reminders(db)
        growth = dispatch.dispatch_due_growth_summaries(db, send_ilink=messaging.send_ilink_text)
    result = {key: legacy[key] + growth[key] for key in ("sent", "paused", "failed")}
    print(json.dumps({"ts": ts, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
