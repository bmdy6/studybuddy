"""家长成长摘要真实 MiMo 验收。"""

import pytest

from app.features.growth.evidence import GrowthEvidence
from app.features.growth.summary import generate_growth_summary


@pytest.mark.live
def test_growth_summary_is_honest_for_empty_and_unmastered_evidence() -> None:
    empty = GrowthEvidence(
        student_id=2,
        student_name="测试学生",
        period="daily",
        period_start="2026-07-12T00:00:00+08:00",
        period_end="2026-07-12T20:30:00+08:00",
    )
    explained_once = GrowthEvidence(
        student_id=2,
        student_name="测试学生",
        period="daily",
        period_start="2026-07-12T00:00:00+08:00",
        period_end="2026-07-12T20:30:00+08:00",
        confirmed_notes=[
            {
                "title": "一次函数讲解记录",
                "subject": "数学",
                "knowledge_tags": ["一次函数"],
            }
        ],
    )

    empty_reply = generate_growth_summary(empty)
    explained_reply = generate_growth_summary(explained_once)

    assert any(word in empty_reply for word in ("没有", "暂无", "未有"))
    assert "已经掌握" not in explained_reply
    assert "已掌握" not in explained_reply
    assert "一次函数" in explained_reply
    assert "{" not in empty_reply + explained_reply
