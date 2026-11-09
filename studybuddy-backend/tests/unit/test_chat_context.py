"""聊天上下文压缩单测。"""

import json

from app.models.chat import ChatMessage, ChatSession
from app.features.chat.context import _compress_messages_for_llm, load_history_as_llm_messages


def _message(role: str, content: str, tool_calls: list[dict] | None = None, tool_result: dict | None = None) -> ChatMessage:
    """构造不依赖数据库连接的聊天消息对象。"""
    return ChatMessage(session_id=1, role=role, content=content, tool_calls=tool_calls, tool_result=tool_result)


def test_short_history_keeps_original_messages():
    """短会话不插入摘要，原样回灌给 LLM。"""
    messages = [
        _message("user", "你好"),
        _message("assistant", "你好，我在"),
    ]

    llm_messages = _compress_messages_for_llm(messages, recent_turns=8)

    assert llm_messages == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我在"},
    ]


def test_long_history_summarizes_older_turns_and_keeps_recent_turns():
    """长会话把旧轮次压缩成 system 摘要，最近轮次保留原文。"""
    messages: list[ChatMessage] = []
    for index in range(6):
        messages.append(_message("user", f"第{index}轮用户消息"))
        messages.append(_message("assistant", f"第{index}轮助手回复"))

    llm_messages = _compress_messages_for_llm(messages, recent_turns=2)

    assert llm_messages[0]["role"] == "system"
    assert "较早对话的压缩摘要" in str(llm_messages[0]["content"])
    assert "第0轮用户消息" in str(llm_messages[0]["content"])
    assert [message["content"] for message in llm_messages[1:]] == [
        "第4轮用户消息",
        "第4轮助手回复",
        "第5轮用户消息",
        "第5轮助手回复",
    ]


def test_summary_preserves_old_batch_id_for_error_import_routing():
    """旧摘要保留 batch_id，供错题导入路由提示继续识别最近批次。"""
    messages = [
        _message("user", "[错题导入] 已上传 2 张照片到批次 #888，请解析。"),
        _message("assistant", "已解析，请问有老师分数吗？"),
    ]
    for index in range(3):
        messages.append(_message("user", f"插入闲聊 {index}"))
        messages.append(_message("assistant", f"闲聊回复 {index}"))
    messages.append(_message("user", "有分数，第3题65分"))

    llm_messages = _compress_messages_for_llm(messages, recent_turns=1)

    assert llm_messages[0]["role"] == "system"
    assert "批次 #888" in str(llm_messages[0]["content"])
    assert llm_messages[-1] == {"role": "user", "content": "有分数，第3题65分"}


def test_tool_call_and_result_stay_in_recent_turn():
    """工具调用和工具结果保留在同一最近轮次内。"""
    tool_calls = [{"id": "call-1", "type": "function", "function": {"name": "query_diagnosis", "arguments": '{"student_id":2}'}}]
    messages = [
        _message("user", "旧问题"),
        _message("assistant", "旧回复"),
        _message("user", "查诊断"),
        _message("assistant", "", tool_calls=tool_calls),
        _message("tool", '{"summary":"暂无错题"}', tool_result={"tool_call_id": "call-1", "name": "query_diagnosis"}),
    ]

    llm_messages = _compress_messages_for_llm(messages, recent_turns=1)

    assert llm_messages[0]["role"] == "system"
    assert llm_messages[1]["role"] == "user"
    assert llm_messages[2]["tool_calls"] == tool_calls
    assert llm_messages[3] == {"role": "tool", "tool_call_id": "call-1", "content": '{"summary":"暂无错题"}'}


def test_recent_large_tool_result_is_truncated_and_total_context_stays_in_budget():
    tool_calls = [
        {
            "id": "call-large",
            "type": "function",
            "function": {"name": "query_error_book", "arguments": '{"student_id":2}'},
        }
    ]
    messages = [
        _message("user", "查一下最近错题"),
        _message("assistant", "", tool_calls=tool_calls),
        _message(
            "tool",
            "错题详情" * 1000,
            tool_result={"tool_call_id": "call-large", "name": "query_error_book"},
        ),
    ]

    llm_messages = _compress_messages_for_llm(
        messages,
        recent_turns=8,
        max_chars=600,
        summary_max_chars=120,
        message_max_chars=160,
        tool_max_chars=100,
    )

    tool_message = next(message for message in llm_messages if message["role"] == "tool")
    assert len(str(tool_message["content"])) <= 103
    assert sum(len(json.dumps(message, ensure_ascii=False)) for message in llm_messages) <= 600


def test_eight_huge_recent_turns_stay_in_total_budget():
    messages: list[ChatMessage] = []
    for index in range(8):
        messages.append(_message("user", f"第{index}轮" + "问题" * 500))
        messages.append(_message("assistant", f"第{index}轮" + "回答" * 500))

    llm_messages = _compress_messages_for_llm(
        messages,
        recent_turns=8,
        max_chars=1200,
        summary_max_chars=240,
        message_max_chars=180,
        tool_max_chars=100,
    )

    assert sum(len(json.dumps(message, ensure_ascii=False)) for message in llm_messages) <= 1200
    assert llm_messages[-1]["content"].startswith("第7轮")


def test_load_history_persists_rolling_summary_and_only_reads_after_marker(db):
    session = ChatSession(
        user_id=1,
        student_id=2,
        role_at_create="student",
        title="长会话",
    )
    db.add(session)
    db.flush()
    for index in range(12):
        decision = "我决定先复习函数再做试卷" if index == 0 else f"第{index}轮问题"
        db.add(ChatMessage(session_id=session.id, role="user", content=decision + "内容" * 200))
        db.add(ChatMessage(session_id=session.id, role="assistant", content=f"第{index}轮回答" + "解释" * 200))
    db.commit()

    first = load_history_as_llm_messages(
        db,
        session.id,
        recent_turns=3,
        max_chars=1400,
        summary_max_chars=500,
        message_max_chars=180,
        tool_max_chars=100,
    )
    db.refresh(session)

    assert session.context_summary_message_id is not None
    assert "我决定先复习函数再做试卷" in (session.context_summary or "")
    first_marker = session.context_summary_message_id

    db.add(ChatMessage(session_id=session.id, role="user", content="继续刚才的安排"))
    db.commit()
    second = load_history_as_llm_messages(
        db,
        session.id,
        recent_turns=3,
        max_chars=1400,
        summary_max_chars=500,
        message_max_chars=180,
        tool_max_chars=100,
    )

    assert first[0]["role"] == "system"
    assert second[0]["content"] == session.context_summary
    assert session.context_summary_message_id == first_marker
    assert second[-1] == {"role": "user", "content": "继续刚才的安排"}


def test_history_repairs_legacy_compact_assistant_text():
    """历史回灌对旧单行 assistant 文本应用适配器，保留换行结构与 compact 顺序。

    防模型模仿坏格式（C1）：LLM 看到的旧消息应已是规范 markdown。
    """
    from app.features.chat.context import _message_to_llm

    legacy = (
        "好的。 --- ### 标题 记住： "
        "1. 第一项 2. 第二项"
    )
    message = _message(role="assistant", content=legacy)
    llm = _message_to_llm(message, message_max_chars=4000, tool_max_chars=2000)
    content = llm["content"]
    assert "---\n" in content, "分隔线换行应保留"
    assert "### 标题" in content, "标题应保留"
    # compact 顺序：修复后的有序列表仍按 1. 2. 排列（防误拆）
    assert "1. 第一项" in content
    assert "2. 第二项" in content


def test_history_keeps_normal_assistant_text_unchanged():
    """已规范 assistant 文本回灌时不被适配器改动（幂等）。"""
    from app.features.chat.context import _message_to_llm

    normal = "好，我们开始。\n\n### 第一块\n\n- 项一\n- 项二"
    message = _message(role="assistant", content=normal)
    llm = _message_to_llm(message, message_max_chars=4000, tool_max_chars=2000)
    assert llm["content"] == normal


def test_history_user_text_not_repaired():
    """user 消息不应用 markdown 适配器（只截断）。"""
    from app.features.chat.context import _message_to_llm

    user_text = "我想学 ### 这个 和 > 那个"
    message = _message(role="user", content=user_text)
    llm = _message_to_llm(message, message_max_chars=4000, tool_max_chars=2000)
    assert llm["content"] == user_text
