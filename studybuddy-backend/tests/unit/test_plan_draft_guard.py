"""计划草案硬边界守卫测试（M0 A+E）。

覆盖（方案 2.2.2 + M0 验收）：
- 文字草案形状纯函数：6 个正例命中 6/6；≥5 个反例（追问/去重建议/解释概念/学习方法/时间概念）误拦 0/5
- 计划协商轮判定（敏感轮）
- agent_loop 接入：首次违规补调成功（draft_tool_succeeded=1、被拒正文 0 SSE/0 持久化）、
  连续两次违规硬失败（draft_rows_created=0、最终正文=固定失败语义）、
  named tool_choice 不支持时走受约束提示重试且不静默退回文字草案、
  工具已成功调 draft_study_plan 时守卫不介入。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import ai_service
from app.features.agent import agent_loop
from app.features.agent.plan_draft_guard import (
    PLAN_GUARD_FAILURE_TEXT,
    is_plan_negotiation_round,
    looks_like_plaintext_draft,
)
from app.models import StudyPlanDraft


async def _async_iter(items):
    """把普通 list 包成 async-iterable，供 `async for chunk in stream` 消费。"""
    for item in items:
        yield item


def _chunk(content=None, reasoning=None, tool_call=None, finish=None):
    """构造一个流式 chunk（OpenAI ChatCompletionChunk）。"""
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
    """构造流式 chunks（包成 async-iterable）：可选正文 + 一个 tool_call。"""
    args_str = json.dumps(tool_input, ensure_ascii=False)
    chunks = []
    if text:
        chunks.append(_chunk(content=text))
    chunks.append(_chunk(tool_call={"index": 0, "id": "call_1", "name": tool_name, "arguments": ""}))
    chunks.append(_chunk(tool_call={"index": 0, "id": None, "name": None, "arguments": args_str}))
    chunks.append(_chunk(finish="tool_calls"))
    return _async_iter(chunks)


def _mock_text_stream(text):
    """构造纯文本流式 chunks（包成 async-iterable）。"""
    return _async_iter([_chunk(content=text), _chunk(finish="stop")])


def _mock_present_response_stream(blocks):
    """构造一次 present_response 工具调用流（结构化终态协议）。"""
    return _mock_tool_stream("present_response", {"blocks": blocks})


# === 纯函数：文字草案形状正例（方案 2.2.2 第 3 条） ===

POSITIVE_DRAFT_TEXTS = [
    "好，草案如下：今日语文·现代文阅读理解训练（2026-08-04）\n- 12分钟：做1篇典型现代文阅读理解真题\n- 8分钟：对答案并分析错因",
    "今日学习计划：数学函数复习\n1. 20分钟：复习函数概念\n2. 15分钟：做3道函数题",
    "好的，计划草案如下，今天安排：\n- 15分钟：背20个单词\n- 25分钟：做两篇阅读理解",
    "今日英语学习计划：一般过去时专项，共 20 分钟\n- 12分钟：语法讲解\n- 8分钟：造句练习",
    "好的，今天的草案：\n1. 25分钟：预习古诗词\n2. 15分钟：背诵并默写",
    "今天的学习计划安排如下：\n- 10分钟：朗读课文\n- 20分钟：赏析练习",
]


@pytest.mark.parametrize("text", POSITIVE_DRAFT_TEXTS)
def test_plan_draft_guard_positive_shapes_hit(text):
    assert looks_like_plaintext_draft(text)


# === 纯函数：反例不得误拦（方案 2.2.2 第 4 条 + M0 去重反例） ===

NEGATIVE_PLAINTEXT_TEXTS = [
    # 粗略意图追问
    "先问几个关键信息：1. 具体目标：想重点提升哪类阅读理解？2. 可用时长：今天打算花多少时间？20分钟、30分钟还是更长？3. 内容偏好：有指定素材吗？",
    # 已有同主题计划的去重建议
    "我查到你已有一个英语·一般过去时的未完成计划，建议先继续那个，不用重新建。",
    # 解释"什么是草案"
    "草案就是先给你看计划草稿，你确认内容没问题后我再正式创建计划。",
    # 普通学习方法
    "学现代文阅读可以先读一遍文章，圈出关键词，再逐题作答，最后对照解析总结错因。",
    # 用户只问时间安排概念
    "一般一天安排多少分钟学习比较合适？",
]


@pytest.mark.parametrize("text", NEGATIVE_PLAINTEXT_TEXTS)
def test_plan_draft_guard_negative_shapes_not_blocked(text):
    assert not looks_like_plaintext_draft(text)


# === 纯函数：计划协商轮判定（方案 2.2.2 第 1 条） ===


def test_plan_draft_guard_sensitive_round_keyword_plan():
    messages = [{"role": "user", "content": "我想学语文阅读理解，帮我做个计划"}]
    assert is_plan_negotiation_round(messages)


def test_plan_draft_guard_sensitive_round_recent_two_rounds():
    messages = [
        {"role": "user", "content": "我想学语文"},
        {"role": "assistant", "content": "想学哪类？"},
        {"role": "user", "content": "现代文，20分钟"},
    ]
    assert is_plan_negotiation_round(messages)


def test_plan_draft_guard_sensitive_round_prior_question():
    messages = [
        {"role": "user", "content": "我想学语文"},
        {"role": "assistant", "content": "具体目标是什么？想重点提升哪类？打算学多久？"},
        {"role": "user", "content": "练记叙文，半个小时"},
    ]
    assert is_plan_negotiation_round(messages)


def test_plan_draft_guard_non_sensitive_round_not_buffered():
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀，有什么可以帮你？"},
        {"role": "user", "content": "今天天气不错"},
    ]
    assert not is_plan_negotiation_round(messages)


# === agent_loop 接入：守卫 + 自动补调 ===


def _count_drafts(db):
    return db.query(StudyPlanDraft).filter(StudyPlanDraft.student_id == 2).count()


def test_plan_draft_guard_first_violation_auto_retry_success(db):
    """首次文字草案违规 -> 自动补调成功调 draft_study_plan。

    draft_tool_succeeded=1、invalid_plaintext_sse_chunks=0、invalid_plaintext_persisted=0。
    """
    streams = [
        _mock_text_stream("好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解\n- 8分钟：分析错因"),
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文阅读理解训练",
                "focus": "记叙文",
                "items": [{"title": "练一篇记叙文阅读", "minutes": 20}],
            },
        ),
        _mock_present_response_stream([{"type": "paragraph", "text": "已生成语文阅读理解草案卡，请确认。"}]),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天学语文阅读理解，20分钟，练记叙文"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    # 结构化草案落库 1 条，draft 工具成功
    assert _count_drafts(db) == 1
    tool_results = [d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"]
    assert len(tool_results) == 1 and tool_results[0]["status"] == "succeeded"
    # 被拒文字草案：0 个 SSE text chunk、0 次进入 Agent 历史
    text_events = [d for t, d in events if t == "text"]
    assert not any("草案如下" in (d.get("content") or "") for d in text_events)
    assert not any(
        m.get("role") == "assistant" and "草案如下" in (m.get("content") or "") for m in result
    )
    # 最终正文收敛为成功确认语
    assert result[-1]["content"] == "已生成语文阅读理解草案卡，请确认。\n"


def test_plan_draft_guard_twice_violation_hard_failure(db):
    """连续两次违规：draft_rows_created=0，最终正文=固定失败语义，不含任务清单。

    tool_choice 形式与受约束形式都仍写文字草案时才算第二次违规。
    """
    streams = [
        _mock_text_stream("好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解\n- 8分钟：分析错因"),
        _mock_text_stream("好的，重新给草案：今日学习计划\n1. 20分钟：复习函数\n2. 15分钟：做练习"),
        _mock_text_stream("好的，再给一份：草案如下，今日学习计划\n- 15分钟：背单词\n- 20分钟：做阅读"),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天学语文阅读理解，20分钟，练记叙文"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 0
    # 最终正文 100% 等于固定失败语义，不含任务清单（分钟）
    assert result[-1]["content"] == PLAN_GUARD_FAILURE_TEXT
    assert "分钟" not in result[-1]["content"]
    # 被拒文字草案不进历史、不闪现
    assert not any(
        m.get("role") == "assistant" and "草案如下" in (m.get("content") or "") for m in result
    )
    text_events = [d for t, d in events if t == "text"]
    assert not any("草案如下" in (d.get("content") or "") for d in text_events)
    assert any(d.get("content") == PLAN_GUARD_FAILURE_TEXT for d in text_events)


def test_plan_draft_guard_named_tool_choice_unsupported_falls_back_to_constrained(db, monkeypatch):
    """named tool_choice 网关不支持（调用抛错）时，走「只保留 draft 工具 + 强纠正提示」重试。

    通过相同断言，不得静默退回文字草案。
    """
    # 加速：工具调用失败的内部重试次数压到 0，避免退避 sleep 拖慢测试
    monkeypatch.setattr(ai_service, "LLM_RETRY_MAX", 0)
    non_tool_streams = [
        _mock_text_stream("好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解"),
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文阅读理解训练",
                "items": [{"title": "练一篇记叙文阅读", "minutes": 20}],
            },
        ),
        _mock_present_response_stream([{"type": "paragraph", "text": "已生成语文阅读理解草案卡，请确认。"}]),
    ]

    def side_effect(*args, **kwargs):
        if kwargs.get("tool_choice"):
            raise RuntimeError("named tool_choice 不被网关支持")
        return non_tool_streams.pop(0)

    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=side_effect):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天学语文阅读理解，20分钟，练记叙文"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 1
    tool_results = [d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"]
    assert len(tool_results) == 1 and tool_results[0]["status"] == "succeeded"
    text_events = [d for t, d in events if t == "text"]
    assert not any("草案如下" in (d.get("content") or "") for d in text_events)
    assert not any(
        m.get("role") == "assistant" and "草案如下" in (m.get("content") or "") for m in result
    )
    assert result[-1]["content"] == "已生成语文阅读理解草案卡，请确认。\n"


def test_plan_draft_guard_tool_choice_silently_ignored_falls_back_to_constrained(db):
    """网关忽略 named tool_choice 仍返回文字时，走受约束提示重试并成功，不静默退回文字草案。"""
    streams = [
        _mock_text_stream("好，草案如下：今日语文学习计划\n- 12分钟：做一篇阅读理解"),
        # tool_choice 形式被网关忽略，仍返回文字草案
        _mock_text_stream("好的，草案如下：今日学习计划\n- 15分钟：背单词\n- 20分钟：做阅读"),
        # 受约束重试成功调 draft_study_plan
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "语文阅读理解训练",
                "items": [{"title": "练一篇记叙文阅读", "minutes": 20}],
            },
        ),
        _mock_present_response_stream([{"type": "paragraph", "text": "已生成语文阅读理解草案卡，请确认。"}]),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天学语文阅读理解，20分钟，练记叙文"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 1
    tool_results = [d for t, d in events if t == "tool_result" and d.get("name") == "draft_study_plan"]
    assert len(tool_results) == 1 and tool_results[0]["status"] == "succeeded"
    text_events = [d for t, d in events if t == "text"]
    assert not any("草案如下" in (d.get("content") or "") for d in text_events)
    assert not any(
        m.get("role") == "assistant" and "草案如下" in (m.get("content") or "") for m in result
    )
    assert result[-1]["content"] == "已生成语文阅读理解草案卡，请确认。\n"


def test_plan_draft_guard_does_not_intervene_when_draft_tool_succeeded(db):
    """LLM 直接成功调 draft_study_plan 时，守卫不介入、按现有工具链继续。"""
    streams = [
        _mock_tool_stream(
            "draft_study_plan",
            {
                "student_id": 2,
                "title": "英语复习",
                "items": [{"title": "背单词", "minutes": 20}],
            },
        ),
        _mock_present_response_stream([{"type": "paragraph", "text": "已生成英语复习草案卡，请确认。"}]),
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=streams):
        result = asyncio.run(
            agent_loop.agent_loop(
                [{"role": "user", "content": "今天学英语，20分钟"}],
                role="student", db=db, teacher_id=2, emit=collect,
            )
        )

    assert _count_drafts(db) == 1
    assert result[-1]["content"] == "已生成英语复习草案卡，请确认。\n"


def test_plan_draft_guard_retry_sanitizes_legacy_plaintext_history(db, monkeypatch):
    """E 修复：补调时历史里的文字草案 assistant 消息必须被替换为占位（只进 LLM 输入）。

    旧会话历史含"草案如下：…"完整示例会诱导 LLM 照抄格式；补调请求发给模型的
    messages 里这些消息应被替换，且不落库、不改会话历史。
    """
    from app.features.agent import agent_loop
    from app.features.agent.plan_draft_guard import PLAINTEXT_DRAFT_PLACEHOLDER

    captured_messages: list[list[dict]] = []

    async def fake_stream(messages, tools, system, **kwargs):
        captured_messages.append(list(messages))
        # 两次补调都仍输出文字草案（模型不配合），最终走硬失败文案
        return _mock_text_stream("好的，今天的草案：\n1. 25分钟：预习古诗词\n2. 15分钟：背诵并默写")

    monkeypatch.setattr(agent_loop.ai_service, "call_llm_stream", fake_stream)

    history = [
        {"role": "user", "content": "帮我定一个学习计划"},
        {"role": "assistant", "content": "好，先问你几个问题：目标、时长、内容偏好？"},
        {"role": "user", "content": "今天学英语 20 分钟，重点语法"},
        # 旧历史里的文字草案示例（诱导源）
        {"role": "assistant", "content": "草案如下：\n**今日英语·语法学习**\n1. 语法梳理（10分钟）\n2. 造句练习（10分钟）"},
    ]
    events: list[tuple[str, dict]] = []

    async def collect(evt_type, data):
        events.append((evt_type, data))

    result = asyncio.run(
        agent_loop.agent_loop(history, role="student", db=db, teacher_id=2, emit=collect)
    )

    # 补调请求里历史草案被占位替换（主轮是原始历史，补调轮才是 sanitized）
    assert len(captured_messages) >= 2, f"应有主轮+补调请求，实际 {len(captured_messages)}"
    for msgs in captured_messages[1:]:
        draft_hist = [m for m in msgs if m.get("role") == "assistant" and "草案如下" in str(m.get("content"))]
        assert not draft_hist, "补调 messages 不应含原始文字草案示例"
        placeholder_hits = [
            m for m in msgs
            if m.get("role") == "assistant" and PLAINTEXT_DRAFT_PLACEHOLDER in str(m.get("content"))
        ]
        assert placeholder_hits, "历史草案应被替换为占位提示"

    # 硬失败：最终正文为固定失败文案，无草案落库
    assert result[-1]["content"] == PLAN_GUARD_FAILURE_TEXT
    assert _count_drafts(db) == 0
