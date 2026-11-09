"""教材事实诚实边界守卫（M2：C 教材诚实边界）。

背景（摸底报告问题2）：live 实测 3 轮 AI 直接断言课本内容（"第8课是《美丽的颜色》"），
不问教材版本、无查证动作，并把未核实断言继续用作计划依据。后端没有课本数据源，
模型预训练记忆不是来源。本模块提供窄规则守卫（方案 2.4/2.5）：

- 教材敏感轮关键词缓冲（只决定是否先缓冲正文，不决定答案）
- 服务端教材证据状态：用户明确陈述 / 当前轮 read_material 结果 / 画像版本
- 确定性断言句式拦截：第X课是《Y》/ 作者是 Y / 根据《Y》这篇课文做计划
- 固定诚实回复 + 一次纠正重试
- draft_study_plan 执行前来源校验 + 服务端覆盖来源标注（context_refs.textbook_source）

边界（方案 2.4.5）：不做自然语言意图理解，不是通用事实核查器；未知句式由 M3/M4
作为升级信号，不扩成自然语言理解模型。只读判断，不做全量教材库。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.prompts import load, render
from .context import _latest_user_content

logger = logging.getLogger(__name__)

# 来源等级（方案 2.4.1）：
#   none / profile_only / user_statement / confirmed_material /
#   auto_ready_material / unconfirmed_material
# 关键边界：教材版本不是目录证据；模型预训练记忆永远不算来源。

# 教材敏感轮触发词（方案 2.4.5.1）：只决定是否缓冲，不决定答案。
TEXTBOOK_SENSITIVE_KEYWORDS = settings.config.agent.textbook_guard.sensitive_keywords

_LESSON_NO_PATTERN = re.compile(r"第\s*([一二三四五六七八九十百\d]+)\s*课")
_LESSON_TITLE_ASSERT = re.compile(
    r"第\s*[一二三四五六七八九十百\d]+\s*课\s*(?:是|为|叫)\s*《[^》]+》"
)
_AUTHOR_ASSERT = re.compile(r"作者\s*(?:是|为|:)\s*[^，。；！？\n]{1,16}")
_PLAN_BASIS_ASSERT = re.compile(r"根据\s*《[^》]+》\s*这篇课文")
_TITLE_BOOK = re.compile(r"《[^》]{1,40}》")

# 疑问或不确定信号：命中即不算确定性断言（方案 2.4.5.3）。
_UNCERTAINTY_HINTS = settings.config.agent.textbook_guard.uncertainty_hints
_QUESTION_HINTS = settings.config.agent.textbook_guard.question_hints

# 有素材来源时的回答约束（方案 2.4.1）：
_OCR_ATTRIBUTION_HINTS = settings.config.agent.textbook_guard.ocr_attribution_hints
_UNCONFIRMED_SAFETY_HINTS = settings.config.agent.textbook_guard.unconfirmed_safety_hints

# 固定诚实兜底文案（方案 2.4.2）：无来源、纠正重试仍违规时使用。
# 模板含 {{lesson}} 占位，正文在 app/prompts/agent/textbook_honesty_fixed_reply.md，用 render() 注入。

# 纠正重试提示（方案 2.4.5.4）：仅本次重试可见，不持久化。
TEXTBOOK_GUARD_CORRECTION_PROMPT = load("agent/textbook_honesty_correction")

# 用户明确陈述的窄格式：第X课(是/为/叫)《Y》。
_USER_STATEMENT_PATTERN = re.compile(
    r"第\s*([一二三四五六七八九十百\d]+)\s*课\s*(?:是|为|叫)?\s*《([^》]+)》"
)

_CS_PATTERN = re.compile(r'"content_source"\s*:\s*"([^"]+)"')
_MID_PATTERN = re.compile(r'"material_id"\s*:\s*(\d+)')


@dataclass
class TextbookEvidence:
    """服务端教材证据状态（方案 2.4.5.2）。"""

    level: str = "none"  # none/profile_only/user_statement/confirmed_material/auto_ready_material/unconfirmed_material
    lesson_no: str = ""
    lesson_title: str | None = None
    author: str | None = None
    material_ids: list[int] = field(default_factory=list)
    user_statement_summary: str | None = None


def is_textbook_sensitive_text(text: str | None) -> bool:
    """教材敏感文本判定（方案 2.4.5.1）：命中只代表该轮先缓冲，不代表答案有错。"""
    if not text or not isinstance(text, str):
        return False
    if any(keyword in text for keyword in TEXTBOOK_SENSITIVE_KEYWORDS):
        return True
    return bool(_LESSON_NO_PATTERN.search(text))


def is_textbook_sensitive_round(messages: list[dict[str, Any]]) -> bool:
    """教材敏感轮判定：最近一条用户消息含教材关键词/第X课。"""
    return is_textbook_sensitive_text(_latest_user_content(messages))


def contains_deterministic_textbook_assertion(text: str | None) -> bool:
    """教材确定性断言句式判定（方案 2.4.5.3）。

    命中：第X课是《Y》 / 作者是 Y / 根据《Y》这篇课文做计划。
    含「无法确认/可能/请核对/是不是」等疑问或不确定句不拦。
    """
    if not text or not isinstance(text, str):
        return False
    if any(hint in text for hint in _UNCERTAINTY_HINTS + _QUESTION_HINTS):
        return False
    return bool(
        _LESSON_TITLE_ASSERT.search(text)
        or _AUTHOR_ASSERT.search(text)
        or _PLAN_BASIS_ASSERT.search(text)
    )


def extract_lesson_no(text: str | None) -> str:
    """从文本里提取第几课的数字（用于固定诚实回复补位）。"""
    if not text or not isinstance(text, str):
        return ""
    match = _LESSON_NO_PATTERN.search(text)
    return match.group(1) if match else ""


def textbook_honesty_fixed_reply(lesson_no: str = "") -> str:
    """无来源时的固定诚实回复（方案 2.4.2）。"""
    lesson = f"第 {lesson_no} 课" if lesson_no else "第 X 课"
    return render("agent/textbook_honesty_fixed_reply", lesson=lesson)


def _extract_user_textbook_statement(text: str) -> tuple[str, str] | None:
    """窄格式提取用户明确陈述（科目/第 X 课/《课名》），返回 (lesson_no, lesson_title)。"""
    if not isinstance(text, str):
        return None
    match = _USER_STATEMENT_PATTERN.search(text)
    if not match:
        return None
    return match.group(1), match.group(2)


def _material_fields_from_tool_content(content: str) -> dict[str, Any] | None:
    """从 read_material 工具结果提取素材证据字段（容忍 LLM 回灌截断）。

    工具输出经 _truncate_for_llm 截断时 JSON 可能不完整，字段在 dict 开头，
    用正则提取 content_source/material_id，不要求完整解析。
    """
    if '"error"' in content:
        return None
    source_match = _CS_PATTERN.search(content)
    if source_match is None and '"content"' not in content:
        return None
    id_match = _MID_PATTERN.search(content)
    return {
        "content_source": source_match.group(1) if source_match else "",
        "material_id": int(id_match.group(1)) if id_match else None,
    }


def _material_evidence_level(content_source: str) -> str:
    if content_source == "confirmed_markdown":
        return "confirmed_material"
    if content_source == "auto_ready_markdown":
        return "auto_ready_material"
    return "unconfirmed_material"


def _extract_material_evidence(messages: list[dict[str, Any]]) -> TextbookEvidence | None:
    """当前轮（最新 user 之后）实际成功的 read_material 结果（方案 2.4.5.2）。

    历史素材不算来源，必须当前轮读取成功；取最近一次结果。
    """
    latest_user_idx = -1
    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            latest_user_idx = index
            break
    read_tool_ids: set[str] = set()
    result: TextbookEvidence | None = None
    for msg in messages[latest_user_idx + 1:]:
        if msg.get("role") == "assistant":
            for tool_call in msg.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                if isinstance(tool_call.get("id"), str) and function.get("name") == "read_material":
                    read_tool_ids.add(tool_call["id"])
        elif msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id")
            content = msg.get("content")
            if not isinstance(tool_call_id, str) or tool_call_id not in read_tool_ids:
                continue
            if not isinstance(content, str):
                continue
            fields = _material_fields_from_tool_content(content)
            if not fields:
                continue
            material_id = fields["material_id"]
            evidence = TextbookEvidence(
                level=_material_evidence_level(fields["content_source"]),
                material_ids=[material_id] if material_id else [],
            )
            result = evidence
    return result


def build_textbook_evidence(
    messages: list[dict[str, Any]],
    profile_versions: dict[str, Any] | None = None,
) -> TextbookEvidence:
    """构建服务端教材证据状态（方案 2.4.5.2）。

    优先当前轮素材结果；其次会话内用户明确陈述（以最新一条为准）；
    再退画像版本（profile_only）；最后 none。模型预训练记忆永远不算来源。
    """
    material = _extract_material_evidence(messages)
    if material is not None:
        return material
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        statement = _extract_user_textbook_statement(content)
        if statement:
            lesson_no, lesson_title = statement
            return TextbookEvidence(
                level="user_statement",
                lesson_no=lesson_no,
                lesson_title=lesson_title,
                user_statement_summary=f"第{lesson_no}课是《{lesson_title}》",
            )
    if profile_versions:
        return TextbookEvidence(level="profile_only")
    return TextbookEvidence(level="none")


def textbook_body_reply_blocked(text: str | None, evidence_level: str) -> bool:
    """正文确定性教材断言是否应拦截（方案 2.4.1 来源分级）。

    none/profile_only：具体课名/作者断言一律拦。
    unconfirmed_material：不带不确定提示的断言拦。
    auto_ready_material：不带 OCR 归因的断言拦。
    user_statement/confirmed_material：放行。
    """
    if not contains_deterministic_textbook_assertion(text):
        return False
    if evidence_level in ("user_statement", "confirmed_material"):
        return False
    if evidence_level == "auto_ready_material":
        return not any(hint in text for hint in _OCR_ATTRIBUTION_HINTS)
    if evidence_level == "unconfirmed_material":
        return not any(hint in text for hint in _UNCONFIRMED_SAFETY_HINTS)
    return True


def _draft_scan_text(args: dict[str, Any]) -> str:
    """把 draft_study_plan 参数拼成扫描文本（title/focus/description/items）。"""
    parts = [
        str(args.get("title") or ""),
        str(args.get("focus") or ""),
        str(args.get("description") or ""),
    ]
    for item in (args.get("items") or []):
        if isinstance(item, dict):
            parts.append(str(item.get("title") or ""))
            parts.append(str(item.get("target") or ""))
    return " ".join(parts)


def check_draft_plan_textbook_source(
    args: dict[str, Any], evidence: TextbookEvidence
) -> str | None:
    """draft_study_plan 执行前教材来源校验（方案 2.4.5.5）。

    教材相关 draft 引用具体课名/作者但证据不足 -> 返回 retryable 拦截文案；
    中性「课本第 X 课」或非教材 draft -> 放行（返回 None）。
    """
    text = _draft_scan_text(args)
    if not is_textbook_sensitive_text(text):
        return None
    has_specific = bool(_TITLE_BOOK.search(text)) or bool(_AUTHOR_ASSERT.search(text))
    if not has_specific:
        return None
    if evidence.level in ("user_statement", "confirmed_material", "auto_ready_material"):
        return None
    if evidence.level == "unconfirmed_material":
        return (
            "计划草案引用了具体课名/作者，但素材识别结果尚未人工确认，不能作为计划依据。"
            "请先让学生确认识别稿，或改用不依赖课名的中性任务（如「课本第 8 课」）。"
        )
    return (
        "计划草案引用了具体课名/作者，但服务端没有可核验的教材目录或用户提供的教材内容。"
        "请先向学生说明无法确认，引导提供教材版本、课名或上传封面版权页、目录、课文页后，再制定计划。"
    )


def _draft_source_note(evidence: TextbookEvidence) -> str:
    if evidence.level == "user_statement":
        return f"计划依据：学生本轮明确提供「{evidence.user_statement_summary}」。"
    if evidence.level == "confirmed_material":
        ids = "、".join(str(i) for i in evidence.material_ids) or "?"
        return f"计划依据：用户上传素材 material_id={ids}（已确认内容）。"
    if evidence.level == "auto_ready_material":
        ids = "、".join(str(i) for i in evidence.material_ids) or "?"
        return f"计划依据：用户上传素材图片的识别结果 material_id={ids}（尚未人工确认，请按学生课本页面执行）。"
    return "内容尚未核验，按学生课本页面执行。"


def annotate_draft_textbook_source(args: dict[str, Any], evidence: TextbookEvidence) -> None:
    """服务端覆盖写入教材来源（方案 2.4.5.6/2.4.5.8）。

    教材相关 draft：把来源/核验说明追加到 description；有有效内容来源时
    覆盖 context_refs.textbook_source（模型自填来源不可信）。中性计划
    只追加「内容尚未核验」说明，不伪造来源。
    """
    text = _draft_scan_text(args)
    if not is_textbook_sensitive_text(text):
        return
    note = _draft_source_note(evidence)
    if note:
        desc = str(args.get("description") or "").strip()
        args["description"] = (desc + "\n" + note).strip() if desc else note
    if evidence.level in ("user_statement", "confirmed_material", "auto_ready_material"):
        refs = dict(args.get("context_refs") or {})
        refs["textbook_source"] = {
            "source_type": evidence.level,
            "lesson_no": evidence.lesson_no or None,
            "lesson_title": evidence.lesson_title,
            "material_ids": evidence.material_ids or None,
            "user_statement": evidence.user_statement_summary,
        }
        args["context_refs"] = refs
