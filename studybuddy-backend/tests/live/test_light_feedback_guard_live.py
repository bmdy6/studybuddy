"""P2 修复 live 复验：轻练轮 record_feedback 必须被拒，feedback 表无新增。

复现：轻练轮 AI 违规调 record_feedback 把负面推断落库（learning_feedback 5395/5396）。
修复后：轻练轮 record_feedback 被 gateway 拒绝（返回错误，不落库）。
"""

import asyncio
import pytest

from app.models.p2 import LearningFeedback
from app.models.user import User
from app.features.chat import agent, sessions
from app.utils.security import hash_password


def _make_student(db) -> User:
    student = User(
        username=f"fb-guard-{abs(hash((id(object()),))) % 10**8}",
        password_hash=hash_password("x"),
        role="student",
        display_name="反馈守卫live",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _tool_names(events: list[tuple[str, dict]]) -> list[str]:
    return [d.get("name") for t, d in events if t == "tool_call" and d.get("name")]


@pytest.mark.live
def test_light_practice_blocks_record_feedback(db) -> None:
    """真实 MiMo：轻练轮 record_feedback 被拒（错误返回），learning_feedback 无新增。"""
    student = _make_student(db)
    session = sessions.create_session(db, student, student.id)
    db.commit()

    fb_count = db.query(LearningFeedback).count()
    events: list[tuple[str, dict]] = []

    async def emit(t: str, d: dict) -> None:
        events.append((t, d))

    async def scenario() -> str:
        await agent.run_agent_turn(db, session, student, "随便练几道口算题吧", emit=emit, auto_title_session=False)
        # 作答推进，触发 AI 在轻练轮内各种行为（含可能违规调 record_feedback）
        for i in range(1, 4):
            await agent.run_agent_turn(db, session, student, f"第{i}道我答：B", emit=emit, auto_title_session=False)
        return ""

    asyncio.run(scenario())

    names = _tool_names(events)
    # 硬边界：feedback 表无新增（无论 AI 是否尝试调 record_feedback）
    assert db.query(LearningFeedback).count() == fb_count, (
        f"轻练轮不得新增 learning_feedback；实际工具={names}"
    )
