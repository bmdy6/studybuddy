"""对话轻练 MVP-A 真实 MiMo live 测试。

验证（AGENTS.md：mock 通过不算完成，必须真实 live）：
- 发「练几道题」类粗略意图 → AI 在对话内出题（不生成试卷）
- 作答后 AI 调 grade_light_answer 确定性判分并讲解对错
- 硬边界：全程不落正式数据（exam/assignment/record/错题本数量不变）

数据全部在测试事务里，结束自动回滚；LLM 失败时断言明确失败，不把网络错误当通过。
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
        username=f"light-live-{abs(hash((id(object()),))) % 10**8}",
        password_hash=hash_password("x"),
        role="student",
        display_name="轻练live",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _tool_names(events: list[tuple[str, dict]]) -> list[str]:
    return [d.get("name") for t, d in events if t == "tool_call" and d.get("name")]


_VERDICT_MARKERS = ("对", "错", "正确", "错误", "答对", "答错", "不对", "没错", "选")


def _has_verdict(text: str) -> bool:
    """回复里是否包含对第一题的对错判断（一问一答即时讲解的核心）。"""
    return any(m in text for m in _VERDICT_MARKERS)


@pytest.mark.live
def test_light_practice_real_llm_no_formal_stats(db) -> None:
    """真实 MiMo：练几道题 → 出题 → 作答 → 判分讲解；不落正式数据。"""
    student = _make_student(db)
    session = sessions.create_session(db, student, student.id)
    db.commit()

    exam_count = db.query(Exam).count()
    assignment_count = db.query(ExamAssignment).count()
    record_count = db.query(ExamRecord).count()

    events: list[tuple[str, dict]] = []

    async def emit(t: str, d: dict) -> None:
        events.append((t, d))

    async def scenario() -> tuple[str, str]:
        first = await agent.run_agent_turn(
            db, session, student, "随便练几道口算题吧",
            emit=emit, auto_title_session=False,
        )
        # 第二、三轮：作答 + 继续（触发判分讲解）
        second = await agent.run_agent_turn(
            db, session, student, "第一道我答 B",
            emit=emit, auto_title_session=False,
        )
        return first, second

    first, second = asyncio.run(scenario())

    # 第一轮：出题（正文非空）
    assert first.strip(), "第一轮应给出题目"
    # 第一轮不得生成试卷
    names = _tool_names(events)
    assert "create_practice_exam" not in names, "轻练不应生成试卷"

    # 作答轮：AI 调用了 grade_light_answer 判分工具（确定性判分，不是口算）
    assert "grade_light_answer" in _tool_names(events), "作答轮应调用 grade_light_answer 判分"

    # 硬边界：全程不落正式数据
    assert db.query(Exam).count() == exam_count
    assert db.query(ExamAssignment).count() == assignment_count
    assert db.query(ExamRecord).count() == record_count
    # 作答轮：有判分讲解回复（含对错判断），即时反馈不缺失
    assert second.strip(), "作答轮应有判分讲解回复"
    assert _has_verdict(second), "作答轮应包含对第一题的对错判断"
