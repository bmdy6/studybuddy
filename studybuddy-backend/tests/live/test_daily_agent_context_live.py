"""每日记录注入学生 Agent 的真实 MiMo 验收。"""

import asyncio
from datetime import date

import pytest

from app.features.agent import agent_loop
from app.features.growth import daily_record_service as daily_learning_record_service


@pytest.mark.live
def test_student_agent_references_yesterday_pending_task_without_inventing_mastery(db):
    record = daily_learning_record_service.get_or_create(db, 2, date(2026, 7, 17))
    record.summary_text = "昨天完成了英语单词复习。"
    record.summary_source = "ai"
    record.facts_snapshot = {
        "student_id": 2,
        "record_date": "2026-07-17",
        "evidence": [{"source_type": "study_plan_item", "source_id": 11, "tier": "self_reported", "title": "英语单词复习"}],
        "pending_tasks": [{"plan_title": "英语计划", "item_title": "复盘错题"}],
        "self_reported_duration_minutes": 0,
        "has_verified_evidence": False,
    }
    db.commit()

    messages = asyncio.run(
        agent_loop.agent_loop(
            [{"role": "user", "content": "我昨天还有什么没做完？只根据每日记录回答，并说清日期。"}],
            role="student",
            db=db,
            teacher_id=2,
        )
    )
    reply = "\n".join(str(msg.get("content") or "") for msg in messages if msg.get("role") == "assistant")

    assert "复盘错题" in reply
    assert "昨天" in reply or "2026-07-17" in reply
    assert "已掌握" not in reply
    assert "明显进步" not in reply
