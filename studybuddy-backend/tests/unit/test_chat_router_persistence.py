"""Chat service 消息持久化单元测试。"""

from app.features.chat import agent


def test_persist_agent_response_messages_keeps_tool_history(monkeypatch):
    """本轮 agent 回复链路会落库工具调用、完整工具结果和最终回复。"""
    persisted: list[dict[str, object]] = []

    def fake_persist_message(
        db,
        session_id: int,
        role: str,
        content: str | None = None,
        tool_calls: list | None = None,
        tool_result: dict | None = None,
    ) -> None:
        """记录持久化调用参数。"""
        persisted.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_calls": tool_calls,
                "tool_result": tool_result,
            }
        )

    monkeypatch.setattr(agent, "persist_message", fake_persist_message)

    agent._persist_agent_response_messages(
        db=object(),
        session_id=7,
        messages=[
            {
                "role": "assistant",
                "content": "查询中",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "query_diagnosis", "arguments": '{"student_id":2}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "截断输出"},
            {"role": "assistant", "content": "暂无错题"},
        ],
        tool_outputs_by_id={"c1": "完整工具输出"},
        emitted_tool_names_by_id={"c1": "query_diagnosis"},
    )

    assert [message["role"] for message in persisted] == ["assistant", "tool", "assistant"]
    assert persisted[0]["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "query_diagnosis", "arguments": '{"student_id":2}'},
        }
    ]
    assert persisted[1]["content"] == "完整工具输出"
    assert persisted[1]["tool_result"] == {"tool_call_id": "c1", "name": "query_diagnosis"}
    assert persisted[2]["content"] == "暂无错题"
