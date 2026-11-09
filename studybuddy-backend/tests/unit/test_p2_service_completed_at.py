"""回归:completed_at 写入口径必须是 naive UTC。

背景:aggregate_daily_facts 用 naive UTC 窗口(utc_start/utc_end)比较
StudyPlanItem.completed_at。若 update_study_plan_item_status 用 datetime.now()
写本地墙上时间,非 UTC 机器上本地晚于 UTC 的完成时间会 > utc_end,落不进当日
窗口,evidence 丢失,每日摘要退回"今天暂时没有新的学习记录"兜底。
"""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.models.p2 import StudyPlan, StudyPlanItem
from app.features.growth import daily_record_service as daily_learning_record_service
from app.features.p2 import study_plan


def _today_local() -> date:
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def test_completed_at_is_naive_utc_after_update_status(db):
    """update_study_plan_item_status 写入的 completed_at 必须是 naive UTC。

    与 DB 的 UTC_TIMESTAMP()(秒级 UTC)对比,差应在数秒内;若误写本地时间,
    非 UTC 环境下会偏移约 8 小时。用真实写入路径,不直接赋固定时间(否则测不到写入口径)。
    MySQL DATETIME 列秒级精度,故对比 DB 的 UTC_TIMESTAMP 而非 Python 微秒时间。
    """
    plan = StudyPlan(student_id=2, title="计划", status="active", planned_date=_today_local())
    db.add(plan)
    db.flush()
    item = StudyPlanItem(plan_id=plan.id, title="口径测试", status="todo")
    db.add(item)
    db.commit()

    study_plan.update_study_plan_item_status(db, item.id, "done")
    db.refresh(item)
    db_utc = db.execute(text("SELECT UTC_TIMESTAMP()")).fetchone()[0]

    assert item.completed_at is not None
    # naive:匹配 MySQL DATETIME 列与 aggregate 的 naive UTC 窗口比较
    assert item.completed_at.tzinfo is None
    assert abs((item.completed_at - db_utc).total_seconds()) < 5, (
        f"completed_at 应近似 UTC_TIMESTAMP,实际 completed_at={item.completed_at} db_utc={db_utc}"
    )


def test_refresh_aggregates_item_just_completed(db, monkeypatch):
    """刚完成的任务必须进当日 evidence(端到端回归)。

    用真实当前时间完成一项任务,验证当日摘要 evidence 含该任务、摘要不再是
    "今天暂时没有新的学习记录"。这是时区 bug 的用户可见现象,跨 UTC/CST 环境均应通过。
    """
    async def generate(_facts):
        return "今天完成了背单词回归。"

    monkeypatch.setattr(
        daily_learning_record_service.daily_summary_service, "generate_summary", generate
    )

    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    today = datetime.now(zone).date()
    plan = StudyPlan(student_id=2, title="今日计划", status="active", planned_date=today)
    db.add(plan)
    db.flush()
    item = StudyPlanItem(plan_id=plan.id, title="背单词回归", status="todo")
    db.add(item)
    db.commit()

    # 被测真实写入路径;now 在写入之后取,保证 utc_end >= completed_at
    study_plan.update_study_plan_item_status(db, item.id, "done")
    now = datetime.now(zone)
    record = asyncio.run(daily_learning_record_service.refresh(db, 2, today, now=now))

    titles = [e.get("title") for e in (record.facts_snapshot or {}).get("evidence", [])]
    assert "背单词回归" in titles, "刚完成的任务应进当日 evidence"
    assert record.summary_text != "今天暂时没有新的学习记录。"
