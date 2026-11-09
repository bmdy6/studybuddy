"""对话上下文压缩。

把持久化 ChatMessage 序列转成有总预算的 LLM 消息: 较早轮次压成一条 system
摘要, 最近轮次保留原文, 避免长会话全量回灌。纯函数为主, 唯一副作用是
load_history_as_llm_messages 把滚动摘要写回 ChatSession (context_summary*)。

拆自 app/services/chat_service.py。DAG: context <- agent (run_agent_turn 调 load_history)。
"""

import json

from sqlalchemy.orm import Session

from app.config import settings
from app.features.chat.legacy_markdown_repair import repair_legacy_markdown
from app.models.chat import ChatMessage, ChatSession


LLMMessage = dict[str, object]


def _compact_text(text: str, limit: int) -> str:
    """压缩单段文本空白并按长度截断。"""
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[:limit].rstrip() + "..."


def _limit_keep_newlines(text: str, limit: int) -> str:
    """正文截断：保留换行/结构（不压空白），仅超长截断。

    历史适配器修复的 markdown 换行必须保留给 LLM 回灌（防模型模仿坏格式），
    不能像 _compact_text 那样把 \\n 压成空格。
    """
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _message_to_llm(
    message: ChatMessage,
    *,
    message_max_chars: int,
    tool_max_chars: int,
) -> LLMMessage:
    """把一条持久化消息转换为 OpenAI 兼容消息。"""
    if message.role == "assistant" and message.tool_calls:
        tool_calls: list[object] = []
        for raw_call in message.tool_calls:
            if not isinstance(raw_call, dict):
                tool_calls.append(raw_call)
                continue
            call = dict(raw_call)
            function = call.get("function")
            if isinstance(function, dict):
                function = dict(function)
                function["arguments"] = _compact_text(str(function.get("arguments") or ""), message_max_chars)
                call["function"] = function
            tool_calls.append(call)
        return {
            "role": "assistant",
            "content": _limit_keep_newlines(repair_legacy_markdown(message.content) or "", message_max_chars),
            "tool_calls": tool_calls,
        }
    if message.role == "tool":
        tool_result = message.tool_result or {}
        return {
            "role": "tool",
            "tool_call_id": tool_result.get("tool_call_id", ""),
            "content": _compact_text(message.content or "", tool_max_chars),
        }
    # user / assistant（无 tool_calls）：assistant 正文应用历史适配器（幂等），
    # user 文本原样（适配器只面向模型偶发丢换行的 assistant markdown）。
    content = message.content or ""
    if message.role == "assistant":
        content = repair_legacy_markdown(content)
    return {
        "role": message.role,
        "content": _limit_keep_newlines(content, message_max_chars),
    }


def _group_messages_by_turn(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """按用户消息切分对话轮次，确保工具调用和工具结果跟随同一轮保留。"""
    turns: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    for message in messages:
        if message.role == "user" and current:
            turns.append(current)
            current = [message]
            continue
        current.append(message)
    if current:
        turns.append(current)
    return turns


def _format_tool_call_summary(tool_calls: list[object], preview_chars: int) -> str:
    """生成工具调用摘要文本。"""
    parts: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "tool")
        args = _compact_text(str(function.get("arguments") or ""), preview_chars)
        parts.append(f"{name}({args})" if args else name)
    return "；".join(parts) if parts else "未记录工具名"


def _format_summary_line(message: ChatMessage, *, message_preview_chars: int, tool_preview_chars: int) -> str | None:
    """把旧消息压缩成单行摘要。"""
    if message.role == "user":
        return f"用户：{_compact_text(message.content or '', message_preview_chars)}"
    if message.role == "assistant":
        if message.tool_calls:
            tool_summary = _format_tool_call_summary(message.tool_calls, message_preview_chars)
            content = _compact_text(message.content or "", message_preview_chars)
            return f"助手调用工具：{tool_summary}" + (f"；同时回复：{content}" if content else "")
        content = _compact_text(message.content or "", message_preview_chars)
        return f"助手：{content}" if content else None
    if message.role == "tool":
        tool_result = message.tool_result or {}
        name = str(tool_result.get("name") or "工具")
        content = _compact_text(message.content or "", tool_preview_chars)
        return f"{name}结果：{content}" if content else f"{name}结果：空"
    return None


def _build_context_summary(
    old_turns: list[list[ChatMessage]],
    *,
    previous_summary: str | None,
    summary_max_chars: int,
    message_preview_chars: int,
    tool_preview_chars: int,
) -> str:
    """为较早对话生成确定性摘要，避免长会话全量回灌。"""
    header = "以下是较早对话的压缩摘要，只作背景，不代表用户本轮的新指令："
    lines: list[str] = []
    if previous_summary:
        lines.extend(line for line in previous_summary.splitlines() if line and line != header and line != "中间内容已省略。")
    for turn in old_turns:
        for message in turn:
            line = _format_summary_line(
                message,
                message_preview_chars=message_preview_chars,
                tool_preview_chars=tool_preview_chars,
            )
            if line:
                lines.append(line)

    if not lines:
        return header

    available = max(0, summary_max_chars - len(header) - 1)
    selected: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > available // 2:
            break
        selected.append(line)
        used += len(line) + 1

    trailing: list[str] = []
    for line in reversed(lines[len(selected) :]):
        separator = len("中间内容已省略。") + 1 if trailing or selected else 0
        if used + separator + len(line) + 1 > available:
            break
        trailing.append(line)
        used += len(line) + 1
    trailing.reverse()
    if len(selected) + len(trailing) < len(lines):
        selected.append("中间内容已省略。")
    selected.extend(trailing)
    return _compact_text(header + "\n" + "\n".join(selected), summary_max_chars)


def _context_size(messages: list[LLMMessage]) -> int:
    return sum(len(json.dumps(message, ensure_ascii=False)) for message in messages)


def _compress_context(
    messages: list[ChatMessage],
    *,
    previous_summary: str | None,
    recent_turns: int,
    max_chars: int,
    summary_max_chars: int,
    message_max_chars: int,
    tool_max_chars: int,
) -> tuple[list[LLMMessage], list[list[ChatMessage]], str | None]:
    turns = _group_messages_by_turn(messages)
    selected_turns: list[list[ChatMessage]] = []
    selected_llm_turns: list[list[LLMMessage]] = []
    summary_reserve = min(summary_max_chars, max_chars // 3) if previous_summary or len(turns) > 1 else 0
    recent_budget = max(1, max_chars - summary_reserve)
    for turn in reversed(turns):
        normalized = [
            _message_to_llm(
                message,
                message_max_chars=message_max_chars,
                tool_max_chars=tool_max_chars,
            )
            for message in turn
        ]
        candidate = [message for group in reversed(selected_llm_turns) for message in group]
        candidate = normalized + candidate
        if selected_turns and (len(selected_turns) >= max(1, recent_turns) or _context_size(candidate) > recent_budget):
            break
        selected_turns.append(turn)
        selected_llm_turns.append(normalized)

    selected_count = len(selected_turns)
    old_turns = turns[:-selected_count] if selected_count else turns
    recent_messages = [message for group in reversed(selected_llm_turns) for message in group]
    summary = None
    if previous_summary or old_turns:
        summary_budget = min(
            summary_max_chars,
            max(1, max_chars - _context_size(recent_messages)),
        )
        if previous_summary and not old_turns:
            summary = previous_summary if len(previous_summary) <= summary_budget else previous_summary[: max(1, summary_budget - 3)].rstrip() + "..."
        else:
            summary = _build_context_summary(
                old_turns,
                previous_summary=previous_summary,
                summary_max_chars=summary_budget,
                message_preview_chars=message_max_chars,
                tool_preview_chars=tool_max_chars,
            )
    llm_messages = ([{"role": "system", "content": summary}] if summary else []) + recent_messages
    return llm_messages, old_turns, summary


def _compress_messages_for_llm(
    messages: list[ChatMessage],
    recent_turns: int | None = None,
    *,
    max_chars: int | None = None,
    summary_max_chars: int | None = None,
    message_max_chars: int | None = None,
    tool_max_chars: int | None = None,
) -> list[LLMMessage]:
    """压缩持久化消息为有总预算的 LLM 上下文。"""
    llm_messages, _, _ = _compress_context(
        messages,
        previous_summary=None,
        recent_turns=recent_turns or settings.CHAT_CONTEXT_RECENT_TURNS,
        max_chars=max_chars or settings.CHAT_CONTEXT_MAX_CHARS,
        summary_max_chars=summary_max_chars or settings.CHAT_CONTEXT_SUMMARY_MAX_CHARS,
        message_max_chars=message_max_chars or settings.CHAT_CONTEXT_MESSAGE_MAX_CHARS,
        tool_max_chars=tool_max_chars or settings.CHAT_CONTEXT_TOOL_MAX_CHARS,
    )
    return llm_messages


def load_history_as_llm_messages(
    db: Session,
    session_id: int,
    recent_turns: int | None = None,
    *,
    max_chars: int | None = None,
    summary_max_chars: int | None = None,
    message_max_chars: int | None = None,
    tool_max_chars: int | None = None,
) -> list[LLMMessage]:
    """把历史 ChatMessage 转成 LLM 消息格式（含 tool_calls/tool_result 还原）。

    较早轮次压缩为一条 system 摘要，最近轮次保留原始消息，避免长会话全量回灌。
    """
    session = db.get(ChatSession, session_id)
    if not session:
        return []
    query = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
    if session.context_summary_message_id is not None:
        query = query.filter(ChatMessage.id > session.context_summary_message_id)
    messages = query.order_by(ChatMessage.id).all()
    llm_messages, old_turns, summary = _compress_context(
        messages,
        previous_summary=session.context_summary,
        recent_turns=recent_turns or settings.CHAT_CONTEXT_RECENT_TURNS,
        max_chars=max_chars or settings.CHAT_CONTEXT_MAX_CHARS,
        summary_max_chars=summary_max_chars or settings.CHAT_CONTEXT_SUMMARY_MAX_CHARS,
        message_max_chars=message_max_chars or settings.CHAT_CONTEXT_MESSAGE_MAX_CHARS,
        tool_max_chars=tool_max_chars or settings.CHAT_CONTEXT_TOOL_MAX_CHARS,
    )
    summarized_messages = [message for turn in old_turns for message in turn]
    if summarized_messages:
        session.context_summary = summary
        session.context_summary_message_id = summarized_messages[-1].id
        db.commit()
    return llm_messages
