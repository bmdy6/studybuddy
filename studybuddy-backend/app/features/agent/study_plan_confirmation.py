"""学习计划草案确认规则。

Agent 工具参数来自模型，不能只靠 prompt 约束。这里集中判断：
用户是否确认了最近的计划草案，以及草案是否仍在短有效期内。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


_CONFIRMATION_PATTERNS = [
    r"可以",
    r"确认",
    r"同意",
    r"就这样",
    r"按这个",
    r"按你说的",
    r"创建吧",
    r"保存吧",
    r"安排吧",
    r"^\s*confirm\s*$",
    r"yes",
    r"ok",
    r"好的",
    r"好呀",
    r"行",
    r"嗯",
]

_DRAFT_MARKERS = [
    "计划草案",
    "是否可行",
    "要不要按这个",
    "可以这样安排",
    "确认后",
    "你觉得这样可以吗",
    # AI 用自然语言给草案的常见表达（不出现「计划草案」字样时）。
    # 这些短语都同时带有「呈现方案 + 等确认才创建」的意图，
    # 不会命中普通讲解/闲聊（如「我帮你讲解这道错题」）。
    "可行就",
    "可行我就",
    "我再创建",
    "帮你创建",
    "这样安排",
]


@dataclass(frozen=True)
class StudyPlanConfirmationResult:
    allowed: bool
    reason: str
    next_step: str


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _message_time(message: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "timestamp", "time"):
        value = message.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue
    return None


def _is_user_confirmation(content: str) -> bool:
    if not content.strip():
        return False
    return any(re.search(pattern, content) for pattern in _CONFIRMATION_PATTERNS)


def _is_plan_draft(content: str) -> bool:
    if not content.strip():
        return False
    return any(marker in content for marker in _DRAFT_MARKERS)


def _plan_draft_content(message: dict[str, Any]) -> str:
    parts = [_message_content(message)]
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if not isinstance(function, dict) or function.get("name") != "present_choice_question":
            continue
        arguments = function.get("arguments")
        try:
            payload = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("question"), str):
            parts.append(payload["question"])
    return "\n".join(parts)


def _latest_user_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message
    return None


def _previous_plan_draft_message(
    messages: list[dict[str, Any]], latest_user: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        latest_index = len(messages) - 1 - list(reversed(messages)).index(latest_user)
    except ValueError:
        latest_index = len(messages)
    for message in reversed(messages[:latest_index]):
        if message.get("role") == "user":
            break
        if message.get("role") == "assistant" and _is_plan_draft(
            _plan_draft_content(message)
        ):
            return message
    return None


def validate_study_plan_confirmation(
    messages: list[dict[str, Any]],
    now: datetime | None = None,
    ttl_minutes: int = 30,
) -> StudyPlanConfirmationResult:
    current_time = now or datetime.now()
    latest_user = _latest_user_message(messages)
    if not latest_user:
        return StudyPlanConfirmationResult(
            allowed=False,
            reason="学习计划需要先给出计划草案并得到用户确认。",
            next_step="请先询问学习目标、可用时长、内容偏好，给出计划草案并等待用户确认。",
        )

    latest_content = _message_content(latest_user)
    if not _is_user_confirmation(latest_content):
        return StudyPlanConfirmationResult(
            allowed=False,
            reason="用户还没有明确确认计划草案。",
            next_step="请先询问学习目标、可用时长、内容偏好，给出计划草案并询问学生是否可行。",
        )

    # 找不到草案不阻塞：AI 措辞多变，_DRAFT_MARKERS 漏识别会导致多计划场景误拒
    # （bug8 回归：AI 最终草案换说法没命中 marker，guard 误判「没给过草案」拒绝创建）。
    # 靠 system_student.md 约束 AI 必须先给草案 + agent_loop 校验 confirmed=true 兜底。
    # 有草案则校验是否过期，避免拿很久以前的草案直接创建。
    draft_message = _previous_plan_draft_message(messages, latest_user)
    if draft_message:
        draft_time = _message_time(draft_message)
        if draft_time is not None and (current_time - draft_time).total_seconds() > ttl_minutes * 60:
            return StudyPlanConfirmationResult(
                allowed=False,
                reason=f"最近的计划草案已过期，超过 {ttl_minutes} 分钟需要重新确认。",
                next_step="请重新给出当前可执行的计划草案，并等待用户再次确认。",
            )

    return StudyPlanConfirmationResult(
        allowed=True,
        reason="用户已确认最近的计划草案。",
        next_step="可以创建学习计划。",
    )
