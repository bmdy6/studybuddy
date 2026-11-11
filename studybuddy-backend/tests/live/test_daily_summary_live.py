"""每日摘要真实 MiMo 边界验收。"""

import asyncio

import pytest

from app.features.growth.daily_summary_service import generate_summary


@pytest.mark.live
def test_daily_summary_does_not_claim_mastery_or_time_without_evidence() -> None:
    facts = {
        "evidence": [{"source_type": "study_plan_item", "source_id": 1, "version": 1, "tier": "self_reported", "title": "完成一次函数练习"}],
        "pending_tasks": [{"plan_title": "今日计划", "item_title": "订正错题"}],
        "self_reported_duration_minutes": 0,
    }
    result = asyncio.run(generate_summary(facts))
    assert result.strip()
    assert "已掌握" not in result
    assert "已经掌握" not in result
    assert "正确率提高" not in result
    assert "分钟" not in result
