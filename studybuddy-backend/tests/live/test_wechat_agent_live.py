"""微信学习助手共享 Agent 真实 MiMo 验收。"""

import asyncio

import pytest

from app.models.user import User
from app.features.chat import agent, sessions


@pytest.mark.live
def test_wechat_student_uses_real_agent_and_learning_data(db) -> None:
    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    session.title = "微信学习助手"
    db.commit()

    async def scenario() -> tuple[str, str]:
        first = await agent.run_agent_turn(
            db,
            session,
            student,
            "我最近总错什么",
            auto_title_session=False,
        )
        second = await agent.run_agent_turn(
            db,
            session,
            student,
            "那我今天先练什么",
            auto_title_session=False,
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert first.strip()
    assert second.strip()
