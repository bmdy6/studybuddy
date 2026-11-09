"""计划草案硬边界守卫（M0：A+E 结构化草案）。

背景：live 实测 6/6 次计划协商只输出纯文字草案、不调 draft_study_plan，
提示词是软约束（模型可能被旧"草案如下"历史诱导）。本模块提供窄规则判定
"文字草案形状"和"计划协商轮"，由 agent_loop 命中后丢弃正文、自动补调一次
draft_study_plan，仍失败返回固定失败文案。

边界（方案 2.2.2）：
- 不做自然语言意图理解；不从文字反解析任务，不直接生成计划参数。
- 只判断观察到的高风险输出形状；不决定是否建计划。
- 与历史无关、不修改历史数据；旧文字草案是无效示例。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.prompts import load
from .date_guard import strip_current_round_date_anchor

logger = logging.getLogger(__name__)

# 固定失败文案（方案 2.2.2 第 8 条）：允许持久化；被拒绝的文字草案不持久化。
PLAN_GUARD_FAILURE_TEXT = load("agent/plan_guard_failure")

# E 修复：补调时用于替换历史文字草案示例的占位（只进本轮 LLM 输入，不落库）。
PLAINTEXT_DRAFT_PLACEHOLDER = load("agent/plan_draft_history_placeholder")

# 补调时的强纠正提示（方案 2.2.2 第 5-6 条）：仅本次补调调用可见，不持久化。
PLAN_GUARD_CORRECTION_PROMPT = load("agent/plan_guard_correction")

# 敏感轮触发词（方案 2.2.2 第 1 条）：只决定"先缓冲再发送"，不决定是否建计划。
PLAN_NEGOTIATION_KEYWORDS = settings.config.agent.plan_guard.negotiation_keywords

# 上一轮正在问目标/时长/内容偏好的提问形状（方案 2.2.2 第 1 条第二半）。
_GOAL_QUESTION_HINTS = settings.config.agent.plan_guard.goal_question_hints

# 正例：计划头部标记（方案 2.2.2 第 3 条）。命中后才可能判为文字草案。
_PLAN_HEADER_PATTERNS = (
    re.compile(r"草案如下"),
    re.compile(r"计划草案"),
    re.compile(r"草案[:：]"),
    re.compile(r"今日学习计划"),
    re.compile(r"今日.{0,8}计划"),
    re.compile(r"今天.{0,8}计划"),
)

# 正例：明确时长分配，如「12 分钟：…」「共 20 分钟」「20分钟、15分钟」。
_TIME_ASSIGNMENT_PATTERNS = (
    re.compile(r"\d+\s*分钟\s*[:：]"),
    re.compile(r"共\s*\d+\s*分钟"),
    re.compile(r"\d+\s*分钟\s*[、,，]"),
)

# 列表式任务行：行首是列表标记，行内含"N 分钟"。
_LIST_LINE_START = re.compile(r"^[-*•·\d一二三四五六七八九十、.．)）]+")
_MINUTES_IN_LINE = re.compile(r"\d+\s*分钟")


def looks_like_plaintext_draft(text: str | None) -> bool:
    """文字草案形状判定（纯函数）。

    同时满足：计划头部标记（草案如下/计划草案/今日学习计划等）+ 明确时长分配
    （或 ≥2 行"列表任务 + 分钟"组合）。追问、去重建议、解释概念、普通学习方法
    因缺少头部标记或时长分配不被拦截。
    """
    if not text or not isinstance(text, str):
        return False
    if not any(pattern.search(text) for pattern in _PLAN_HEADER_PATTERNS):
        return False
    if any(pattern.search(text) for pattern in _TIME_ASSIGNMENT_PATTERNS):
        return True
    return _count_minute_task_lines(text) >= 2


def _count_minute_task_lines(text: str) -> int:
    """统计"列表标记 + N 分钟"的任务行数。"""
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not _LIST_LINE_START.match(stripped) or not _MINUTES_IN_LINE.search(stripped):
            continue
        count += 1
    return count


def is_plan_negotiation_round(messages: list[dict[str, Any]]) -> bool:
    """计划协商轮判定（方案 2.2.2 第 1 条）。

    最近两轮用户消息含触发词（计划/草案/安排/今天学/分钟/改成/不要这个），
    或上一轮 assistant 正在问目标/时长/内容偏好。只决定是否缓冲正文，不决定建计划。
    """
    user_texts: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        text = strip_current_round_date_anchor(content).strip()
        if text:
            user_texts.append(text)
    for content in user_texts[-2:]:
        if any(keyword in content for keyword in PLAN_NEGOTIATION_KEYWORDS):
            return True
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and any(hint in content for hint in _GOAL_QUESTION_HINTS):
            return True
        break
    return False
