"""对话 Agent 编排。

run_agent_turn 串起消息持久化 -> 上下文加载 (context) -> agent_loop 执行 ->
本轮响应落库。消息写入 (persist_message / _persist_agent_response_messages)
归此, 因强耦合 run_agent_turn。

拆自 app/services/chat_service.py。DAG: agent -> context (load_history_as_llm_messages),
agent -> sessions (maybe_auto_title), agent -> app.features.agent.agent_loop。
"""

from typing import Any

from sqlalchemy.orm import Session

from app.features.agent import agent_loop, date_guard
from app.features.agent.context import _PRACTICE_EXAM_ROUTE_HINT, _ROUTE_HINT_INJECTED_MARKER, _build_task_context
from app.features.chat.context import load_history_as_llm_messages
from app.features.chat.sessions import maybe_auto_title
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User


def persist_message(
    db: Session, session_id: int, role: str, content: str | None = None, tool_calls: list | None = None, tool_result: dict | None = None
) -> ChatMessage:
    """持久化一条消息。"""
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_result=tool_result,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _tool_names_from_agent_messages(messages: list[dict[str, Any]]) -> dict[str, str]:
    """从 Agent 消息中提取工具调用 ID 到工具名的映射。"""
    names: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_id = tool_call.get("id")
            function = tool_call.get("function")
            if not isinstance(tool_call_id, str) or not isinstance(function, dict):
                continue
            name = function.get("name")
            if isinstance(name, str) and name:
                names[tool_call_id] = name
    return names


def _persist_agent_response_messages(
    db: Session,
    session_id: int,
    messages: list[dict[str, Any]],
    tool_outputs_by_id: dict[str, str],
    emitted_tool_names_by_id: dict[str, str],
) -> None:
    """持久化本轮 Agent 追加的 assistant/tool 消息。"""
    tool_names_by_id = _tool_names_from_agent_messages(messages)
    tool_names_by_id.update(emitted_tool_names_by_id)

    for message in messages:
        role = message.get("role")
        if role == "assistant":
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            normalized_content = content if isinstance(content, str) else None
            normalized_tool_calls = tool_calls if isinstance(tool_calls, list) else None
            # P1 修复：路由约束提示是注入给 LLM 的服务端指令，不落库、不展示给学生。
            # 命中条件：稳定标记（注入时置于正文开头，LLM 截断回显必带）或模板正文前缀（
            # 极端情况 LLM 丢标记仅转述正文开头时兜底）；兼容旧标记（[路由约束]）。
            _route_prefix = _PRACTICE_EXAM_ROUTE_HINT[:12]
            if normalized_content and (
                _ROUTE_HINT_INJECTED_MARKER in normalized_content
                or normalized_content.startswith(_route_prefix)
                or "[路由约束]" in normalized_content
            ):
                continue
            if normalized_content or normalized_tool_calls:
                persist_message(
                    db,
                    session_id,
                    "assistant",
                    content=normalized_content,
                    tool_calls=normalized_tool_calls,
                )
            continue

        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue
            fallback_output = message.get("content")
            content = tool_outputs_by_id.get(tool_call_id) or (fallback_output if isinstance(fallback_output, str) else "")
            persist_message(
                db,
                session_id,
                "tool",
                content=content,
                tool_result={
                    "tool_call_id": tool_call_id,
                    "name": tool_names_by_id.get(tool_call_id, "tool"),
                },
            )


def _inject_current_round_date_anchor(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """M1：复制本轮 messages，仅给最新一条 user 消息加服务端日期锚点前缀。

    锚点只进本次 LLM 输入（消息列表副本）；原始用户文本仍按现状落库和展示。
    agent_loop 多轮工具调用共用同一列表，锚点自然沿用整轮（不重新注入）。
    """
    anchored = list(messages)
    for index in range(len(anchored) - 1, -1, -1):
        message = anchored[index]
        if message.get("role") != "user":
            continue
        copy = dict(message)
        raw = copy.get("content") or ""
        copy["content"] = f"{date_guard.current_round_date_anchor()}{raw}"
        anchored[index] = copy
        break
    return anchored


def _correct_final_assistant_text(
    response_messages: list[dict[str, Any]], user_content: str
) -> None:
    """M1：最终文本窄范围校正（原地修改），只把明确称为「今天」的过去日期改为今天。

    仅在最新用户消息含「今天/今日」时启用，避免改动普通日期问答；
    只校正最终 assistant 正文（无 tool_calls 的最后一条），落库与 done.content 都返回校正后文本。
    """
    if not date_guard.should_correct_today_label(user_content):
        return
    for message in reversed(response_messages):
        is_final_assistant = (
            message.get("role") == "assistant"
            and not message.get("tool_calls")
            and isinstance(message.get("content"), str)
        )
        if is_final_assistant:
            message["content"] = date_guard.correct_today_label_in_text(message["content"])
            break


async def run_agent_turn(
    db: Session,
    session: ChatSession,
    user: User,
    content: str,
    emit: agent_loop.EventHandler | None = None,
    *,
    display_content: str | None = None,
    auto_title_session: bool = True,
    business_actor: str | None = None,
) -> str:
    """使用现有 Agent 执行一轮对话并保存完整消息链。"""
    normalized = content.strip() if content else ""
    # 冷启动自动触发会发空 content（前端 skipUserMessage）：允许空，agent 按注入的冷启动指令回话

    display_normalized = (display_content or normalized).strip() or normalized
    # 模式驱动：user.mode == hobby → business_actor=hobby（兴趣模式：兴趣提示词+资源搜索工具）
    if business_actor is None and getattr(user, "mode", "study") == "hobby":
        business_actor = "hobby"
    persist_message(db, session.id, "user", content=display_normalized)
    if auto_title_session:
        maybe_auto_title(db, session, display_normalized)

    history = load_history_as_llm_messages(db, session.id)
    if display_normalized != normalized:
        for message in reversed(history):
            if message.get("role") == "user":
                message["content"] = normalized
                break
    # M1 当前轮日期锚点：复制本轮 messages，只对最新一条 user 消息加隐藏前缀。
    # 前缀只进本次 LLM 输入（不落库、不展示），原始用户文本保持现状。
    llm_messages = _inject_current_round_date_anchor(history)
    response_start_index = len(llm_messages)
    tool_outputs_by_id: dict[str, str] = {}
    emitted_tool_names_by_id: dict[str, str] = {}

    async def capture_and_emit(evt_type: str, data: dict[str, Any]) -> None:
        if evt_type == "tool_call":
            tool_call_id = data.get("id")
            name = data.get("name")
            if isinstance(tool_call_id, str) and isinstance(name, str):
                emitted_tool_names_by_id[tool_call_id] = name
        elif evt_type == "tool_result":
            tool_call_id = data.get("id")
            output = data.get("output")
            name = data.get("name")
            if isinstance(tool_call_id, str):
                if isinstance(output, str):
                    tool_outputs_by_id[tool_call_id] = output
                if isinstance(name, str):
                    emitted_tool_names_by_id[tool_call_id] = name
        if emit:
            await emit(evt_type, data)

    # U-042：task session 走任务执行分支，注入 task 上下文（计划说明 + 任务目标 + 相关知识点 + 稳定画像）
    session_type = getattr(session, "session_type", "main")
    task_context = _build_task_context(db, session) if session_type == "task" else ""
    updated = await agent_loop.agent_loop(
        messages=llm_messages,
        role=user.role,
        db=db,
        teacher_id=user.id,
        student_id=session.student_id,
        emit=capture_and_emit,
        business_actor=business_actor,
        session_type=session_type,
        task_context=task_context,
        chat_session_id=session.id,
    )
    response_messages = updated[response_start_index:]
    # M1 最终文本窄范围校正：持久化和 done.content 都返回校正后文本，与数据库保持一致。
    # 结构化终态协议下，assistant 正文已在 agent_loop 内确定性渲染，此处校正作用于渲染后文本（E1 顺序：渲染→校正→落库）。
    _correct_final_assistant_text(response_messages, normalized)
    _persist_agent_response_messages(
        db,
        session.id,
        response_messages,
        tool_outputs_by_id,
        emitted_tool_names_by_id,
    )

    for message in reversed(response_messages):
        final_content = message.get("content")
        is_final_assistant = message.get("role") == "assistant" and not message.get("tool_calls")
        if is_final_assistant and isinstance(final_content, str) and final_content:
            return final_content
    return ""
