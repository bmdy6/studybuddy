import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.models.p2 import StudyPlan, StudyPlanItem
from app.features.growth import daily_record_service as daily_learning_record_service
from app.features.growth import daily_summary_service


def _response(content: str | None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _add_pending_plan(db):
    plan = StudyPlan(student_id=2, title="合成待学计划", status="active", planned_date=date(2026, 7, 18))
    db.add(plan)
    db.flush()
    db.add(StudyPlanItem(plan_id=plan.id, title="背单词", status="todo"))
    db.commit()


def test_empty_facts_never_call_model_and_keep_record_contract(db, monkeypatch):
    generate = AsyncMock(return_value="This must not become learning evidence")
    monkeypatch.setattr(daily_summary_service, 'generate_summary', generate)
    first = asyncio.run(daily_learning_record_service.refresh(db, 2, date(2026, 7, 17)))
    second = asyncio.run(daily_learning_record_service.refresh(db, 2, date(2026, 7, 17)))
    generate.assert_not_called()
    assert first.id == second.id
    assert second.summary_text == "今天暂时没有新的学习记录。"
    assert second.summary_source == "deterministic"
    assert second.generation_status == "ready"
    assert second.generated_at is not None
    assert second.evidence_hash
    assert not daily_summary_service.has_learning_facts(second.facts_snapshot)


def test_generate_summary_only_sends_structured_facts(monkeypatch):
    captured = {}

    async def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return _response("今天完成了背单词。")

    monkeypatch.setattr(daily_summary_service.ai_service, "call_llm", fake_call_llm)
    facts = {
        "evidence": [{"source_type": "study_plan_item", "source_id": 1, "version": 1, "tier": "self_reported", "title": "背单词"}],
        "pending_tasks": [],
        "self_reported_duration_minutes": 0,
    }

    result = asyncio.run(daily_summary_service.generate_summary(facts))

    assert result == "今天完成了背单词。"
    assert "背单词" in captured["messages"][0]["content"]
    assert "旧摘要" not in captured["messages"][0]["content"]
    assert "已经掌握" in captured["system"]


@pytest.mark.parametrize("failure", [RuntimeError("down"), TimeoutError("slow")])
def test_refresh_uses_deterministic_fallback_on_llm_failure(db, monkeypatch, failure):
    _add_pending_plan(db)
    async def fail(_facts):
        raise failure

    monkeypatch.setattr(daily_learning_record_service.daily_summary_service, "generate_summary", fail)
    record = asyncio.run(
        daily_learning_record_service.refresh(
            db, 2, date(2026, 7, 18), now=datetime(2026, 7, 18, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        )
    )

    assert record.summary_source == "deterministic"
    assert record.generation_status == "ready"
    assert "1 项未完成" in record.summary_text


def test_refresh_uses_fallback_for_empty_llm_text(db, monkeypatch):
    _add_pending_plan(db)
    async def empty(_facts):
        return "   "

    monkeypatch.setattr(daily_learning_record_service.daily_summary_service, "generate_summary", empty)
    record = asyncio.run(daily_learning_record_service.refresh(db, 2, date(2026, 7, 18)))
    assert record.summary_source == "deterministic"
    assert "1 项未完成" in record.summary_text


def test_refresh_skips_llm_when_evidence_hash_is_unchanged(db, monkeypatch):
    _add_pending_plan(db)
    calls = 0

    async def generate(_facts):
        nonlocal calls
        calls += 1
        return "第一版摘要"

    monkeypatch.setattr(daily_learning_record_service.daily_summary_service, "generate_summary", generate)
    now = datetime(2026, 7, 18, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = asyncio.run(daily_learning_record_service.refresh(db, 2, date(2026, 7, 18), now=now))
    second = asyncio.run(daily_learning_record_service.refresh(db, 2, date(2026, 7, 18), now=now))

    assert first.id == second.id
    assert calls == 1
    assert second.summary_text == "第一版摘要"


def test_refresh_updates_same_record_when_evidence_changes(db, monkeypatch):
    _add_pending_plan(db)
    summaries = iter(["第一版摘要", "第二版摘要"])

    async def generate(_facts):
        return next(summaries)

    monkeypatch.setattr(daily_learning_record_service.daily_summary_service, "generate_summary", generate)
    record_date = date(2026, 7, 18)
    now = datetime(2026, 7, 18, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = asyncio.run(daily_learning_record_service.refresh(db, 2, record_date, now=now))
    first_hash = first.evidence_hash

    plan = StudyPlan(student_id=2, title="今日计划", status="active", planned_date=record_date)
    db.add(plan)
    db.flush()
    db.add(StudyPlanItem(plan_id=plan.id, title="背单词", status="done", completed_at=datetime(2026, 7, 18, 9)))
    db.commit()

    second = asyncio.run(daily_learning_record_service.refresh(db, 2, record_date, now=now))
    assert second.id == first.id
    assert second.evidence_hash != first_hash
    assert second.summary_text == "第二版摘要"
    assert second.summary_source == "ai"


def test_deterministic_summary_keeps_pending_visible_without_inventing_duration():
    text = daily_summary_service.deterministic_summary(
        {
            "evidence": [{"tier": "self_reported", "title": "背单词"}],
            "pending_tasks": [{"item_title": "订正错题"}],
            "self_reported_duration_minutes": 0,
        }
    )
    assert "背单词" in text
    assert "1 项未完成" in text
    assert "掌握" not in text
    assert "分钟" not in text
