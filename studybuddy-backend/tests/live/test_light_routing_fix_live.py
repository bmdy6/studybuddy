"""P1 修复 live 复验：轻练会话后发「做一套卷子」必须走 create_practice_exam 建卷。

复现 bug 场景（docs/22-bug/[P1-高][修复中]主会话-轻练后试卷路由被上下文污染.md）：
轻练走完 3 题后发「做一套卷子」→ 必须调 create_practice_exam 生成自练卷
（修复前：被轻练上下文带偏，查计划/查错题本 + 口头追问，不建卷）。
"""

import asyncio
import pytest

from app.models.exam import Exam
from app.models.exam_assignment import ExamAssignment
from app.models.exam_record import ExamRecord
from app.models.user import User
from app.features.chat import agent, sessions
from app.utils.security import hash_password


def _make_student(db) -> User:
    student = User(
        username=f"route-fix-{abs(hash((id(object()),))) % 10**8}",
        password_hash=hash_password("x"),
        role="student",
        display_name="路由修复live",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _tool_names(events: list[tuple[str, dict]]) -> list[str]:
    return [d.get("name") for t, d in events if t == "tool_call" and d.get("name")]


@pytest.mark.live
def test_paper_request_after_light_practice_builds_exam(db) -> None:
    """真实 MiMo：轻练 3 题后发「做一套卷子」→ create_practice_exam 建卷（P1 复现修复验证）。"""
    student = _make_student(db)
    session = sessions.create_session(db, student, student.id)
    db.commit()

    events: list[tuple[str, dict]] = []

    async def emit(t: str, d: dict) -> None:
        events.append((t, d))

    async def scenario() -> str:
        # 轻练：随便练几道（AI 出题，我们在对话里作答推进，答满多轮确保轻练结束）
        await agent.run_agent_turn(db, session, student, "随便练几道口算题吧", emit=emit, auto_title_session=False)
        for i in range(1, 5):
            await agent.run_agent_turn(
                db, session, student, f"第{i}道我答：选 B", emit=emit, auto_title_session=False
            )
        # 关键：轻练结束之后发「做一套卷子」
        reply = await agent.run_agent_turn(db, session, student, "做一套卷子", emit=emit, auto_title_session=False)
        return reply

    reply = asyncio.run(scenario())

    names = _tool_names(events)
    assert "create_practice_exam" in names, (
        f"轻练后发「做一套卷子」必须调 create_practice_exam 建卷；实际工具={names}\n回复={reply[:300]}"
    )
    assert reply.strip(), "建卷轮应有正文回复"

    # 路由约束是服务端注入指令：不得落库展示给学生（含截断回显正文开头——稳定标记在注入消息开头）
    from app.models.chat import ChatMessage
    from app.features.agent.context import _PRACTICE_EXAM_ROUTE_HINT, _ROUTE_HINT_INJECTED_MARKER

    persisted = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).all()
    route_prefix = _PRACTICE_EXAM_ROUTE_HINT[:12]
    leaked = [
        m.content
        for m in persisted
        if m.content
        and (
            _ROUTE_HINT_INJECTED_MARKER in m.content
            or m.content.startswith(route_prefix)
            or "[路由约束]" in m.content
        )
    ]
    assert not leaked, f"路由约束消息不应落库：{leaked}"
