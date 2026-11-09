"""共享单轮 Agent 编排测试。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.chat import ChatMessage
from app.models.user import User
from app.features.chat import agent, sessions


async def _async_iter(items):
    for item in items:
        yield item


def _chunk(content=None, reasoning=None, tool_call=None, finish=None):
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning
    delta.tool_calls = None
    if tool_call is not None:
        tc = MagicMock()
        tc.index = tool_call.get("index", 0)
        tc.id = tool_call.get("id")
        tc.function = MagicMock()
        tc.function.name = tool_call.get("name")
        tc.function.arguments = tool_call.get("arguments")
        delta.tool_calls = [tc]
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _mock_tool_stream(tool_name, tool_input, text=""):
    args_str = json.dumps(tool_input, ensure_ascii=False)
    chunks = []
    if text:
        chunks.append(_chunk(content=text))
    chunks.append(_chunk(tool_call={"index": 0, "id": "call_1", "name": tool_name, "arguments": ""}))
    chunks.append(_chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


def _mock_text_stream(text):
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _mock_present_response_stream(blocks):
    return _mock_tool_stream("present_response", {"blocks": blocks})


def test_run_agent_turn_persists_user_tool_and_final_messages(db, monkeypatch):
    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)

    async def fake_agent_loop(messages, *, emit, **_kwargs):
        tool_call = {
            "id": "t1",
            "type": "function",
            "function": {"name": "query_errors", "arguments": "{}"},
        }
        messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
        await emit(
            "tool_result",
            {"id": "t1", "name": "query_errors", "output": "完整错题数据"},
        )
        messages.extend(
            [
                {"role": "tool", "tool_call_id": "t1", "content": "截断错题数据"},
                {"role": "assistant", "content": "你最近常错一次函数。"},
            ]
        )
        return messages

    monkeypatch.setattr(agent.agent_loop, "agent_loop", fake_agent_loop)

    result = asyncio.run(
        agent.run_agent_turn(db, session, student, "我最近错什么")
    )

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    )
    assert result == "你最近常错一次函数。"
    assert [item.role for item in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1].tool_calls[0]["id"] == "t1"
    assert messages[2].content == "完整错题数据"
    assert messages[2].tool_result == {"tool_call_id": "t1", "name": "query_errors"}


def test_run_agent_turn_persists_display_content_but_sends_protocol_value_to_agent(db, monkeypatch):
    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    captured_messages = []

    async def fake_agent_loop(messages, **_kwargs):
        captured_messages.extend(messages)
        messages.append({"role": "assistant", "content": "我们开始数学。"})
        return messages

    monkeypatch.setattr(agent.agent_loop, "agent_loop", fake_agent_loop)

    asyncio.run(
        agent.run_agent_turn(
            db,
            session,
            student,
            "math",
            display_content="数学",
        )
    )

    persisted_user = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.role == "user")
        .one()
    )
    assert persisted_user.content == "数学"
    # M1：发给 LLM 的消息带本轮日期锚点前缀，但落库/展示仍是原文
    from app.features.agent import date_guard

    anchor = date_guard.current_round_date_anchor()
    assert captured_messages[-1]["content"] == anchor + "math"
    assert anchor not in (persisted_user.content or "")


def test_run_agent_turn_passes_channel_guardian_actor_to_agent(db, monkeypatch):
    guardian = db.get(User, 1)
    session = sessions.create_session(db, guardian, 2)
    captured = {}

    async def fake_agent_loop(messages, **kwargs):
        captured.update(kwargs)
        messages.append({"role": "assistant", "content": "最近学习正常。"})
        return messages

    monkeypatch.setattr(agent.agent_loop, "agent_loop", fake_agent_loop)

    result = asyncio.run(
        agent.run_agent_turn(
            db,
            session,
            guardian,
            "孩子最近怎么样",
            business_actor="channel_guardian",
        )
    )

    assert result == "最近学习正常。"
    assert captured["business_actor"] == "channel_guardian"
    assert captured["student_id"] == 2


def test_historical_plaintext_draft_still_produces_structured_draft(db):
    """带旧"草案如下"历史（E）：仍成功出结构化 draft；旧消息数据库内容不变。"""
    from app.core import ai_service
    from app.models import StudyPlanDraft

    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    # 预置旧版无效文字草案历史（同摸底 testreg 的污染样本）
    agent.persist_message(db, session.id, "user", content="我想学语文阅读理解")
    agent.persist_message(db, session.id, "assistant", content="好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解\n- 8分钟：分析错因")
    before = [
        (m.role, m.content)
        for m in db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    ]

    streams = [
        # 第一轮被旧历史诱导，继续写文字草案 -> 守卫命中
        _mock_text_stream("好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解\n- 8分钟：分析错因"),
        # 补调成功调 draft_study_plan，真实落库
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文阅读理解训练",
                "focus": "记叙文",
                "items": [{"title": "练一篇记叙文阅读", "minutes": 20}],
            },
        ),
        _mock_present_response_stream(
            [{"type": "paragraph", "text": "已生成语文阅读理解草案卡，请确认。"}]
        ),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        final = asyncio.run(
            agent.run_agent_turn(
                db, session, student, "今天学语文阅读理解，20分钟，练记叙文", emit=collect
            )
        )

    # 旧消息数据库内容不变（前 N 条与跑前完全一致）
    after = [
        (m.role, m.content)
        for m in db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    ]
    assert after[: len(before)] == before
    # 被拒的文字草案没有持久化（旧历史之外无新的"草案如下"assistant 消息）
    new_messages = after[len(before):]
    assert not any(
        role == "assistant" and content and "草案如下" in content for role, content in new_messages
    )
    # 被拒正文 0 个 SSE chunk
    text_events = [d for t, d in events if t == "text"]
    assert not any("草案如下" in (d.get("content") or "") for d in text_events)
    # 结构化草案落库，done.content 收敛为成功确认语
    drafts = db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == 2).all()
    assert len(drafts) == 1
    assert drafts[0].draft_data["title"] == "语文阅读理解训练"
    assert final == "已生成语文阅读理解草案卡，请确认。\n"


def test_study_plan_dedup_suggests_continue_not_forced_new_card(db):
    """去重反例：已有同主题未完成计划时建议继续，守卫不得强制出新卡。"""
    from app.core import ai_service
    from app.features.p2 import study_plan as study_plan_service
    from app.features.p2.schemas import StudyPlanItemInput
    from app.models import StudyPlanDraft

    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    # 预置同主题未完成计划（英语·一般过去时）
    study_plan_service.create_study_plan(
        db,
        student_id=2,
        title="今日英语语法补漏·一般过去时",
        items=[StudyPlanItemInput(title="复习一般过去时", minutes=20)],
        focus="一般过去时",
        created_by=2,
    )

    streams = [
        # 第一轮查已有计划
        _mock_tool_stream("query_study_plans", {"student_id": 2, "status": "active"}),
        # 第二轮给去重建议（无计划草案形状，守卫不得拦截）
        _mock_text_stream(
            "我查到你已有一个「今日英语语法补漏·一般过去时」的未完成计划，建议先继续那个。1. 继续 2. 重新建一个"
        ),
    ]

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent.run_agent_turn(db, session, student, "今天学英语一般过去时，20分钟")
        )

    # 守卫不拦截去重建议：0 条新草案落库，正文是继续建议而非新卡
    assert db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == 2).count() == 0
    assert "继续那个" in result
    assert "重新建一个" in result


def test_present_response_persists_content_without_tool_calls(db):
    """E2：present_response 终态只落渲染后 content，不落 tool_calls。

    防刷新历史出现"present_response 工具卡"（协议工具不是业务动作）。
    """
    from app.core import ai_service

    student = db.get(User, 2)
    session = sessions.create_session(db, student, student.id)
    streams = [
        _mock_present_response_stream(
            [
                {"type": "paragraph", "text": "对！你判断对了。"},
                {"type": "heading", "level": 3, "text": "第二块：抛物线与顶点"},
                {"type": "list", "ordered": False, "items": ["a > 0：开口朝上", "a < 0：开口朝下"]},
            ]
        ),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        final = asyncio.run(
            agent.run_agent_turn(db, session, student, "3", emit=collect)
        )

    assert "### 第二块：抛物线与顶点" in final
    assert "- a > 0：开口朝上" in final
    # 落库：content 是渲染后文本，tool_calls 为空（不落协议工具）
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    )
    assistant_msgs = [m for m in messages if m.role == "assistant"]
    assert len(assistant_msgs) >= 1
    latest = assistant_msgs[-1]
    assert "### 第二块" in (latest.content or "")
    assert not latest.tool_calls
    # SSE text 事件与 done.content 一致
    text_events = [d.get("content") for t, d in events if t == "text"]
    assert text_events and text_events[-1] == final
