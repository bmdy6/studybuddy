import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.core import ai_service
from app.features.agent import agent_loop
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.user import User
from app.features.growth import daily_record_service as daily_learning_record_service


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _record(db, student_id: int, record_date: date, *, summary: str | None = None, pending=None):
    record = daily_learning_record_service.get_or_create(db, student_id, record_date)
    record.summary_text = summary
    record.summary_source = "ai" if summary else None
    record.facts_snapshot = {
        "student_id": student_id,
        "record_date": record_date.isoformat(),
        "evidence": [],
        "pending_tasks": pending or [],
        "self_reported_duration_minutes": 0,
        "has_verified_evidence": False,
    }
    db.commit()
    return record


def test_build_agent_context_includes_yesterday_today_plan_and_recent_trend(db):
    yesterday = date(2026, 7, 17)
    yesterday_record = _record(
        db,
        2,
        yesterday,
        summary="昨天完成了英语单词复习。",
        pending=[{"plan_title": "英语计划", "item_title": "复盘错题"}],
    )
    yesterday_record.facts_snapshot = {
        **yesterday_record.facts_snapshot,
        "evidence": [{"title": "英语单词复习", "source_type": "study_plan_item"}],
    }
    db.commit()
    _record(db, 2, yesterday - timedelta(days=1), summary="不应注入的更早摘要")
    _record(db, 2, yesterday - timedelta(days=2), summary="也不应注入的历史摘要")

    plan = StudyPlan(student_id=2, title="今天数学计划", status="active", planned_date=NOW.date())
    db.add(plan)
    db.flush()
    db.add(StudyPlanItem(plan_id=plan.id, title="做函数题", status="todo", sort_order=1))
    db.add(StudyPlanItem(plan_id=plan.id, title="看错题讲解", status="done", sort_order=2))
    db.commit()

    context = daily_learning_record_service.build_agent_context(db, 2, now=NOW)

    assert "2026-07-17" in context
    assert "昨天完成了英语单词复习" in context
    assert "复盘错题" in context
    assert "今天数学计划" in context
    assert "做函数题" in context
    assert "看错题讲解（已完成）" in context
    assert "不应注入的更早摘要" not in context
    assert "也不应注入的历史摘要" not in context
    assert "AI摘要" in context
    assert "事实区" in context
    assert "近期7天事实趋势" in context


def test_build_agent_context_without_records_is_empty(db):
    assert daily_learning_record_service.build_agent_context(db, 2, now=NOW) == ""


def test_build_agent_context_treats_naive_now_as_service_timezone(db):
    _record(db, 2, date(2026, 7, 16), summary="本地昨天摘要")
    _record(db, 2, date(2026, 7, 17), summary="不应作为本地昨天")

    context = daily_learning_record_service.build_agent_context(
        db,
        2,
        now=datetime(2026, 7, 17, 23, 30),
    )

    assert "本地昨天摘要" in context
    assert "不应作为本地昨天" not in context


def test_build_agent_context_isolates_students(db):
    other = User(username="daily_context_other", password_hash="test", role="student")
    db.add(other)
    db.flush()
    _record(db, other.id, date(2026, 7, 17), summary="另一个学生的摘要")

    context = daily_learning_record_service.build_agent_context(db, 2, now=NOW)

    assert "另一个学生的摘要" not in context


def test_build_agent_context_dedupes_entries_and_honors_length_limit(db):
    pending = [{"plan_title": "计划", "item_title": "重复任务"}] * 20
    _record(db, 2, date(2026, 7, 17), summary="重复摘要。" * 300, pending=pending)

    context = daily_learning_record_service.build_agent_context(db, 2, now=NOW, max_chars=420)

    assert len(context) <= 420
    assert context.count("重复任务") == 1
    assert 1 < context.count("重复摘要") < 300
    assert "…" in context


def test_agent_loop_injects_daily_context_for_student():
    captured_system = ""

    async def _stream(text):
        delta = SimpleNamespace(content=text, reasoning_content=None, tool_calls=None)
        choice = SimpleNamespace(delta=delta)
        yield SimpleNamespace(choices=[choice])

    async def _present_stream(text):
        # present_response 工具调用流（结构化终态协议）
        args_str = json.dumps({"blocks": [{"type": "paragraph", "text": text}]}, ensure_ascii=False)
        tc = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="present_response", arguments=args_str))
        delta = SimpleNamespace(content=None, reasoning_content=None, tool_calls=[tc])
        choice = SimpleNamespace(delta=delta)
        yield SimpleNamespace(choices=[choice])

    async def fake_stream(*args, **kwargs):
        nonlocal captured_system
        captured_system = kwargs.get("system") or args[2]
        return _present_stream("收到")

    with (
        patch.object(agent_loop, "_build_profile_context", return_value=""),
        patch.object(agent_loop, "_build_learning_memory_context", return_value=""),
        patch.object(
            agent_loop,
            "_build_daily_learning_record_context",
            return_value="\n[每日学习记录] 事实区（日期=2026-07-17）：未完成任务：复盘错题",
        ),
        patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream),
    ):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "接着昨天的任务"}],
                role="student",
                db=MagicMock(),
                teacher_id=2,
            )
        )

    assert "复盘错题" in captured_system
    assert result[-1]["content"] == "收到\n"


def test_daily_context_read_failure_is_skipped():
    with patch(
        "app.features.agent.context.daily_learning_record_service.build_agent_context",
        side_effect=RuntimeError("db unavailable"),
    ):
        assert agent_loop._build_daily_learning_record_context(MagicMock(), 2) == ""
