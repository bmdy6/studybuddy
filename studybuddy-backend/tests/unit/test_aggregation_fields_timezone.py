"""回归:聚合路径剩余 3 个时间字段写入口径必须是 naive UTC。

aggregate_daily_facts 用 naive UTC 窗口(utc_start/utc_end)比较 4 个字段;
completed_at 已在 test_p2_service_completed_at.py 覆盖。本文件覆盖剩余 3 个:
  Material.recognized_at / Note.created_at / LearningFeedback.created_at
并加跨 4 字段的 TZ=Asia/Shanghai 端到端回归(cst_environment 同时钉 Python 进程
与 MySQL session 时区为 +08:00,模拟非 UTC 服务器)。

根因:若任一字段写 naive 本地时间(datetime.now() 或 func.now()=MySQL NOW()),
非 UTC 机器上本地晚于 UTC 的记录会 > utc_end,落不进当日窗口,evidence 丢失,
每日摘要退回"今天暂时没有新的学习记录"兜底。
"""

import asyncio
import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.material import Material
from app.models.note import Note
from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem
from app.models.user import User
from app.features.materials import extraction_service, service as material_service
from app.features.growth import daily_record_service as daily_learning_record_service
from app.features.note import service as note_service
from app.features.p2 import feedback, study_plan
from app.features.materials.markdown_extraction_service import MarkdownExtractionResult


def _today_local() -> date:
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def _db_utc(db) -> datetime:
    """DB 的 UTC_TIMESTAMP()——始终返回 UTC,与 session time_zone 无关,作为 naive UTC 基准。"""
    return db.execute(text("SELECT UTC_TIMESTAMP()")).fetchone()[0]


def _assert_naive_utc(stored, db, label: str) -> None:
    """断言 stored 是 naive UTC:naive 且近似 DB 的 UTC_TIMESTAMP()(秒级,数秒内)。"""
    assert stored is not None, f"{label} 不应为 None"
    assert stored.tzinfo is None, f"{label} 必须是 naive(对齐 MySQL DATETIME 列与聚合窗口)"
    db_utc = _db_utc(db)
    assert abs((stored - db_utc).total_seconds()) < 5, (
        f"{label} 应近似 UTC_TIMESTAMP,实际 {label}={stored} db_utc={db_utc}"
    )


@pytest.fixture
def cst_environment(db):
    """模拟 CST 服务器:Python 进程 TZ=Asia/Shanghai + MySQL session time_zone='+08:00'。

    在此环境下,任何写 naive 本地时间的字段都会偏离 UTC,被 aggregate 的 naive UTC
    窗口过滤掉:
      - datetime.now()(Python 本地)-> 返回 CST naive(回归 completed_at/recognized_at 时命中)
      - func.now()=MySQL NOW() -> 返回 session CST(回归 Note/LearningFeedback created_at 时命中)
    UTC_TIMESTAMP() 始终返回 UTC,与 naive UTC 口径对比即可判定写入口径。
    """
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset 不可用(非 Unix)")
    saved_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    db.execute(text("SET time_zone='+08:00'"))
    try:
        yield
    finally:
        db.execute(text("SET time_zone='SYSTEM'"))
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()


def test_note_created_at_is_naive_utc(cst_environment, db):
    """note_service.create_note 写入的 created_at 必须是 naive UTC,而非 MySQL NOW()=CST。"""
    note_service.create_note(db, {"student_id": 2, "title": "时区测试笔记", "status": "confirmed"})
    note = db.query(Note).filter(Note.student_id == 2, Note.title == "时区测试笔记").one()
    _assert_naive_utc(note.created_at, db, "Note.created_at")


def test_learning_feedback_created_at_is_naive_utc(cst_environment, db):
    """feedback.submit_feedback 写入的 created_at 必须是 naive UTC,而非 MySQL NOW()=CST。"""
    feedback.submit_feedback(db, student_id=2, feedback_type="duration", content="30分钟")
    fb = (
        db.query(LearningFeedback)
        .filter(LearningFeedback.student_id == 2)
        .order_by(LearningFeedback.id.desc())
        .first()
    )
    _assert_naive_utc(fb.created_at, db, "LearningFeedback.created_at")


def _make_recognized_material(db, tmp_path, monkeypatch, *, name="时区测试素材", markdown="背单词素材识别内容"):
    """构造一张本地图片素材,mock OCR,走 ensure_extraction 真实写入路径,返回 material。

    确保 auto_ready=True(高置信无不确定点),使该素材能进 aggregate 的 Material evidence。
    """
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG 魔数即可过扩展名/存在性校验(OCR 已 mock)
    material = Material(
        name=name,
        type="image",
        source="student",
        content_ref="local:page.png",
        recognition_status="pending",
        uploaded_by=2,
        student_id=2,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    # 跳过本地路径解析与真实 OCR,直接喂识别结果,聚焦测 recognized_at 写入口径
    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(image))

    async def fake_recognize(_image_paths, mode="learning_material"):
        return MarkdownExtractionResult(
            markdown=markdown,
            raw_text=markdown,
            confidence="high",
            uncertain_points=[],
            content_type="study_note",
            provider="mock",
        )

    monkeypatch.setattr("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", fake_recognize)

    user = db.get(User, 2)
    asyncio.run(extraction_service.ensure_extraction(db, material.id, user))
    db.refresh(material)
    return material


def test_recognized_at_is_naive_utc(cst_environment, db, tmp_path, monkeypatch):
    """material_service 识别素材后 recognized_at 必须是 naive UTC,而非 datetime.now()=CST。"""
    material = _make_recognized_material(db, tmp_path, monkeypatch)
    _assert_naive_utc(material.recognized_at, db, "Material.recognized_at")


def test_refresh_aggregates_all_fields_under_cst(cst_environment, db, tmp_path, monkeypatch):
    """CST 服务器下,刚完成的 4 类记录(任务/笔记/素材/时长反馈)必须全部进当日 evidence。

    端到端回归:Python TZ=Asia/Shanghai + MySQL session=+08:00,任一字段若写 naive 本地
    时间都会被 naive UTC 窗口过滤,evidence 缺该条。跨 UTC/CST 环境均应通过(本测试强制 CST)。
    """
    async def generate(_facts):
        return "今天完成了背单词全套记录。"

    monkeypatch.setattr(
        daily_learning_record_service.daily_summary_service, "generate_summary", generate
    )

    today = _today_local()
    # 1. 完成计划项(completed_at)
    plan = StudyPlan(student_id=2, title="今日计划", status="active", planned_date=today)
    db.add(plan)
    db.flush()
    item = StudyPlanItem(plan_id=plan.id, title="背单词", status="todo")
    db.add(item)
    db.commit()
    study_plan.update_study_plan_item_status(db, item.id, "done")

    # 2. 确认笔记(Note.created_at)
    note_service.create_note(db, {"student_id": 2, "title": "背单词笔记", "status": "confirmed"})

    # 3. 识别素材(Material.recognized_at)
    _make_recognized_material(db, tmp_path, monkeypatch, name="背单词素材", markdown="背单词素材内容")

    # 4. 时长反馈(LearningFeedback.created_at,_minutes("30分钟")=30)
    feedback.submit_feedback(db, student_id=2, feedback_type="duration", content="30分钟")

    # 被测真实写入路径;now 在写入之后取,保证 utc_end >= 各字段时间
    now = datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE))
    record = asyncio.run(daily_learning_record_service.refresh(db, 2, today, now=now))

    facts = record.facts_snapshot or {}
    titles = [e.get("title") for e in facts.get("evidence", [])]

    facts = record.facts_snapshot or {}
    titles = [e.get("title") for e in facts.get("evidence", [])]
    assert "背单词" in titles, f"CST 下完成的任务应进 evidence,实际 evidence={titles}"
    assert "背单词笔记" in titles, f"CST 下确认的笔记应进 evidence,实际 evidence={titles}"
    assert "背单词素材" in titles, f"CST 下识别的素材应进 evidence,实际 evidence={titles}"
    assert facts.get("self_reported_duration_minutes", 0) >= 30, (
        f"CST 下提交的时长反馈应计入 duration,实际 duration={facts.get('self_reported_duration_minutes')}"
    )
    assert record.summary_text != "今天暂时没有新的学习记录。"
