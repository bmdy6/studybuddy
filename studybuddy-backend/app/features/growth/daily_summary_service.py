"""从每日结构化事实生成学生可读摘要。"""

import json
import logging
from typing import Any

from app.config import settings
from app.core import ai_service
from app.prompts import load

logger = logging.getLogger(__name__)


def has_learning_facts(facts: dict[str, Any]) -> bool:
    """是否有真实学习事实（evidence/pending/duration 任一非空）。"""
    evidence = facts.get("evidence") or []
    pending = facts.get("pending_tasks") or []
    duration = facts.get("self_reported_duration_minutes") or 0
    return bool(evidence or pending or duration)


def deterministic_summary(facts: dict[str, Any]) -> str:
    if not has_learning_facts(facts):
        return "今天暂时没有新的学习记录。"

    evidence = facts.get("evidence") or []
    pending = facts.get("pending_tasks") or []
    duration = facts.get("self_reported_duration_minutes") or 0
    sections: list[str] = []
    if duration:
        sections.append(f"今天记录了 {duration} 分钟的学习。")
    if evidence:
        titles = [str(item.get("title") or "") for item in evidence if item.get("title")]
        if titles:
            sections.append("今天完成或记录了：" + "、".join(titles) + "。")
        else:
            sections.append("今天有新的学习记录。")
    if pending:
        titles = [str(item.get("item_title") or "") for item in pending if item.get("item_title")]
        suffix = "：" + "、".join(titles) if titles else ""
        sections.append(f"截至当前还有 {len(pending)} 项未完成{suffix}。")
    return "\n".join(sections)


async def generate_summary(facts: dict[str, Any]) -> str:
    response = await ai_service.call_llm(
        messages=[{"role": "user", "content": "请生成每日学习摘要。结构化真实事实：" + json.dumps(facts, ensure_ascii=False, sort_keys=True)}],
        system=load("growth/daily_summary"),
        max_tokens=settings.DAILY_RECORD_SUMMARY_MAX_TOKENS,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(getattr(choices[0], "message", None), "content", None)
    return content.strip() if isinstance(content, str) else ""
