"""长会话压缩后的真实 MiMo 连贯性验收。"""

import asyncio

import pytest

from app.core import ai_service
from app.models.chat import ChatMessage
from app.features.chat.context import _compress_messages_for_llm


@pytest.mark.live
def test_compressed_long_history_preserves_explicit_user_decision() -> None:
    messages: list[ChatMessage] = []
    for index in range(12):
        content = "我决定今天先复习函数，再做一套试卷。" if index == 0 else f"这是第{index}轮普通学习讨论。" + "补充内容" * 80
        messages.append(ChatMessage(session_id=1, role="user", content=content))
        messages.append(
            ChatMessage(
                session_id=1,
                role="assistant",
                content=f"收到第{index}轮信息。" + "说明" * 80,
            )
        )

    history = _compress_messages_for_llm(
        messages,
        recent_turns=3,
        max_chars=1800,
        summary_max_chars=600,
        message_max_chars=220,
        tool_max_chars=120,
    )
    history.append(
        {
            "role": "user",
            "content": "我之前明确决定今天先做什么？只根据对话回答，不要编造。",
        }
    )

    response = asyncio.run(ai_service.call_llm(history, max_tokens=120))
    reply = response.choices[0].message.content or ""

    assert "函数" in reply
    assert "试卷" in reply
