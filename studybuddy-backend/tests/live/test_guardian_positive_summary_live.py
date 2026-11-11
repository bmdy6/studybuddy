import time

import pytest

from app.features.growth import summary


@pytest.mark.live
def test_guardian_positive_summary_is_encouraging_without_inventing_progress() -> None:
    facts = {
        "student_id": 2,
        "record_date": "2026-07-18",
        "evidence": [
            {
                "source_type": "material",
                "source_id": 10,
                "tier": "machine_extracted",
                "title": "英语单词表",
            }
        ],
        "pending_tasks": [{"item_title": "订正错题"}],
        "self_reported_duration_minutes": 0,
        "has_verified_evidence": False,
    }

    started = time.perf_counter()
    result = summary.generate_guardian_positive_summary(facts)
    elapsed = time.perf_counter() - started

    assert result.strip()
    assert "1" in result or "一" in result
    assert "未完成" in result or "订正错题" in result
    for forbidden in ("已经掌握", "明显进步", "正确率提高", "学习了30分钟"):
        assert forbidden not in result
    print(f"guardian positive summary live elapsed={elapsed:.2f}s")
