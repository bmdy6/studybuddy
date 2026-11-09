from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import settings
from app.core import ai_service

from .evidence import GrowthEvidence
from app.prompts import load

logger = logging.getLogger(__name__)


def deterministic_guardian_positive_summary(facts: dict[str, Any]) -> str:
    """Facts-only fallback; machine evidence is explicitly kept below verified facts."""
    evidence = facts.get("evidence") or []
    pending = facts.get("pending_tasks") or []
    duration = facts.get("self_reported_duration_minutes") or 0
    trusted = [item for item in evidence if item.get("tier") in {"verified", "self_reported"}]
    machine = [item for item in evidence if item.get("tier") == "machine_extracted"]
    period_label = "本周" if facts.get("period") == "weekly" else "今天"
    sections: list[str] = []
    if trusted:
        titles = [str(item.get("title")) for item in trusted if item.get("title")]
        sections.append(f"{period_label}真实记录了：" + "、".join(titles) + "。" if titles else f"{period_label}有可核对的学习记录。")
        sections.append("愿意开始并完成一项具体学习行动，这一点值得肯定。")
        if machine:
            sections.append(f"{period_label}还整理了 {len(machine)} 份机器识别素材，先作为复习参考保存。")
    elif machine:
        sections.append(f"{period_label}整理了 {len(machine)} 份机器识别素材，先作为复习参考保存。")
        sections.append("愿意把素材整理起来，是一个可以继续的小行动。")
    elif duration:
        sections.append(f"{period_label}记录了 {duration} 分钟的学习，但具体内容暂未记录。")
        sections.append("愿意记录学习时长，说明已经开始关注自己的学习过程。")
    else:
        sections.append(f"{period_label}暂时没有新的学习记录。")
    if pending:
        pending_count = len(pending)
        sections.append(f"截至推送时间尚有 {pending_count} 项未完成。")
        sections.append("可以先一起选一项最轻松的任务开始，不必一次做完全部。")
    else:
        sections.append("可以问问孩子明天想从哪一小步开始。")
    return "\n".join(sections)


def generate_guardian_positive_summary(facts: dict[str, Any]) -> str:
    """Generate the parent-facing positive summary with a deterministic fallback."""

    async def collect_content() -> str:
        prefix = "请生成家长成长摘要。以下是结构化事实（AI 摘要仅作辅助表述，不能当作事实）："
        prompt = f"{prefix}{json.dumps(facts, ensure_ascii=False, sort_keys=True)}"
        response = await ai_service.call_llm(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            system=load("growth/guardian_positive"),
            max_tokens=settings.WECHAT_GROWTH_SUMMARY_MAX_TOKENS,
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        content = getattr(getattr(choices[0], "message", None), "content", None)
        return content.strip() if isinstance(content, str) else ""

    try:
        result = asyncio.run(collect_content())
    except Exception:  # noqa: BLE001 - parent messaging must degrade to facts
        logger.warning("家长正向成长摘要生成失败，使用事实兜底", exc_info=True)
        result = ""
    result = result or deterministic_guardian_positive_summary(facts)
    pending = facts.get("pending_tasks") or []
    if facts.get("period") and pending and "截至推送时间尚有" not in result:
        result += f"\n截至推送时间尚有 {len(pending)} 项未完成。"
    return result


def generate_growth_summary(evidence: GrowthEvidence) -> str:
    system = load("growth/growth_summary")

    async def collect_content() -> str:
        stream = await ai_service.call_llm_stream(
            messages=[
                {
                    "role": "user",
                    "content": "请生成成长摘要。真实证据：" + json.dumps(evidence.model_dump(), ensure_ascii=False),
                }
            ],
            system=system,
            max_tokens=settings.WECHAT_GROWTH_SUMMARY_MAX_TOKENS,
        )
        parts: list[str] = []
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if isinstance(content, str):
                parts.append(content)
        return "".join(parts).strip()

    content = asyncio.run(collect_content())
    if not content:
        raise RuntimeError("成长摘要生成失败")
    return content
