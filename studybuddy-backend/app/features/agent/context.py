"""Agent 上下文构建（注入 LLM system prompt 的学生画像/学习记忆/错题导入/每日回顾）。

拆自 app/core/agent_loop.py。主循环 agent_loop() 调本模块 _build_*_context 拼装 system
增强上下文，_forced_*_tool 做高置信意图强制工具注入。跨域共享辅助（_resolve_tool_student_id
被各 handler 调用）也在此。
依赖方向：单向依赖 features/services（p2/error_book/note_service/materials 等易变业务），
故随 agent_loop 一并迁出 core（修 #1#2 反向依赖）。note_service/error_book/User/material_service
在函数内按需 import（避免顶层耦合 + 循环）。
"""
import json
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import access_service
from app.features.growth import daily_record_service as daily_learning_record_service
from app.features.p2 import attribute, feedback, interests, profile
from app.prompts import load, render
from .date_guard import strip_current_round_date_anchor
from .study_plan_confirmation import validate_study_plan_confirmation

logger = logging.getLogger(__name__)

_WRONG_REASON_PREFIX = "错题原因"


def _is_wrong_reason_feedback(content: str, feedback_type: str) -> bool:
    """识别结果页记录的错因反馈。"""
    return feedback_type == "difficulty" and content.strip().startswith(_WRONG_REASON_PREFIX)


def _format_wrong_reason_feedback(content: str, max_len: int = 120) -> str:
    """压缩错因反馈，避免 system context 过长。"""
    compact = " ".join(content.split())
    return compact if len(compact) <= max_len else compact[: max_len - 1] + "…"



def _resolve_tool_student_id(args: dict[str, Any], role: str, db: Session, user_id: int) -> int:
    """统一解析 Agent 工具里的 student_id。

    student 调工具时永远只能用自己；teacher 必须传绑定学生 id。
    """
    if role == "student":
        return user_id
    student_id = int(args.get("student_id") or 0)
    if not student_id:
        return 0
    if not access_service.teacher_can_access_student(db, user_id, student_id):
        raise PermissionError("无权访问该学生")
    return student_id


def _format_day_label(value: date) -> str:
    return f"{value.year}.{value.month}.{value.day}"


def _is_daily_review_for_target_date(note: Any, target_date: date) -> bool:
    """判断一条每日回顾是否对应目标日期。

    新格式以目标日期命名笔记，并在正文写入“今日目标（日期）”。旧格式里可能出现
    “日期 目标”，但那代表旧版目标日期，不能用来判断当天已经写过新每日回顾。
    """
    day_label = _format_day_label(target_date)
    title = note.title or ""
    content = note.content or ""
    return title.startswith(f"{day_label} 每日回顾") or f"今日目标（{day_label}）" in content


_LEARNING_MEMORY_SKIP_KEYWORDS = (
    "登录",
    "账号",
    "切换账号",
    "帮助页面",
    "帮助与更新",
    "打不开",
    "报错",
)


def _should_include_learning_memory(latest_user_text: str) -> bool:
    text = (latest_user_text or "").strip()
    if not text:
        return False
    if any(keyword in text for keyword in _LEARNING_MEMORY_SKIP_KEYWORDS):
        return False
    return True


def _shorten_learning_memory_text(value: Any, limit: int = 100) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    if limit == 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


def _summarize_error_book_groups(groups: list[Any], limit: int = 5) -> list[str]:
    items: list[dict[str, Any]] = []
    for group in groups or []:
        tag = getattr(group, "tag", "") or ""
        for question in getattr(group, "questions", []) or []:
            items.append(
                {
                    "tag": tag,
                    "error_id": getattr(question, "error_id", ""),
                    "stem": getattr(question, "stem", ""),
                    "student_answer": getattr(question, "student_answer", ""),
                    "correct_answer": getattr(question, "correct_answer", ""),
                    "error_count": int(getattr(question, "error_count", 0) or 0),
                }
            )
    items.sort(key=lambda item: item["error_count"], reverse=True)
    lines: list[str] = []
    for item in items[:limit]:
        parts = [
            f"error_id={item['error_id']}",
            f"知识点={_shorten_learning_memory_text(item['tag'] or '未标注', 24)}",
            f"题干={_shorten_learning_memory_text(item['stem'], 100)}",
        ]
        if item["student_answer"]:
            parts.append(f"学生答案={_shorten_learning_memory_text(item['student_answer'], 100)}")
        if item["correct_answer"]:
            parts.append(f"正确答案={_shorten_learning_memory_text(item['correct_answer'], 100)}")
        parts.append(f"错过 {item['error_count']} 次")
        lines.append("，".join(parts))
    return lines


def _summarize_error_review_notes(notes: list[Any], limit: int = 3) -> list[str]:
    review_notes = [
        note
        for note in notes or []
        if getattr(note, "category", None) == "错题复盘" or getattr(note, "source", None) == "错题讲解"
    ]
    lines: list[str] = []
    for note in review_notes[:limit]:
        raw_title = getattr(note, "title", "") or ""
        raw_content = getattr(note, "content", "") or ""
        title = _shorten_learning_memory_text(raw_title, 24)
        prefix = f"《{title or '未命名复盘'}》"
        content_limit = max(0, 120 - len(prefix) - 1)
        content = _shorten_learning_memory_text(raw_content, content_limit) if content_limit else ""
        if title or content:
            lines.append(f"{prefix}：{content}" if content else prefix)
    return lines


def _material_status_label(status: str | None) -> str:
    labels = {
        "confirmed": "已确认",
        "recognized": "已识别待确认",
        "needs_review": "需核对",
        "processing": "识别中",
        "failed": "识别失败",
        "pending": "待识别",
    }
    return labels.get((status or "pending").strip(), status or "待识别")


def _material_ai_readiness(status: str | None) -> str:
    if status == "confirmed":
        return "可直接用于复习/讲解"
    if status in {"recognized", "needs_review"}:
        return "可参考，但建议先确认识别稿"
    if status == "failed":
        return "识别失败，需要重新识别或手动描述"
    return "暂不可直接读取内容，需要先识别成 Markdown"


def _summarize_material_memory_items(materials: list[Any], limit: int = 3) -> list[str]:
    lines: list[str] = []
    for material in (materials or [])[:limit]:
        material_id = getattr(material, "id", "")
        name = _shorten_learning_memory_text(getattr(material, "name", "") or "未命名素材", 24)
        mtype = getattr(material, "type", "") or "unknown"
        status = getattr(material, "recognition_status", None)
        tags = getattr(material, "knowledge_tags", None) or []
        tag_text = "、".join([str(tag) for tag in tags[:3] if tag])
        parts = [f"#{material_id}", name, mtype, _material_status_label(status)]
        if tag_text:
            parts.append(f"标签={_shorten_learning_memory_text(tag_text, 32)}")
        lines.append("，".join(parts))
    return lines


def _build_learning_memory_section(
    title: str,
    items: list[str],
    *,
    numbered: bool = False,
    total_limit: int,
    item_limit: int | None = None,
    preserve_items: bool = False,
) -> str:
    if not items:
        return ""

    prefix = f"{title}："
    remaining = total_limit - len(prefix)
    if remaining <= 0:
        return ""

    section_items: list[str] = []
    for index, item in enumerate(items):
        entry = f"{index + 1}. {item}" if numbered else item
        if item_limit is not None and not preserve_items:
            entry = _shorten_learning_memory_text(entry, item_limit)
        needed = len(entry) + (1 if section_items else 0)
        if needed > remaining:
            if not section_items and not preserve_items:
                section_items.append(_shorten_learning_memory_text(entry, remaining))
            break
        section_items.append(entry)
        remaining -= needed

    return prefix + "；".join(section_items) if section_items else ""


def _build_learning_memory_context(db: Session, student_id: int, latest_user_text: str) -> str:
    if not _should_include_learning_memory(latest_user_text):
        return ""
    try:
        from app.models.user import User
        from app.features.materials import service as material_service
        from app.features.note import service as note_service
        from app.features.error_book.service import get_error_book

        parts: list[str] = []
        user = db.get(User, student_id) if hasattr(db, "get") else None
        if user:
            try:
                material_lines = _summarize_material_memory_items(material_service.list_materials(db, user), limit=3)
            except Exception:  # noqa: BLE001
                logger.warning("读取素材记忆失败：student_id=%s", student_id, exc_info=True)
                material_lines = []
            if material_lines:
                material_section = _build_learning_memory_section(
                    "最近素材",
                    material_lines,
                    numbered=True,
                    total_limit=260,
                    item_limit=90,
                )
                if material_section:
                    parts.append(material_section)

        blind_spots = note_service.get_blind_spots(db, student_id, min_errors=2)[:5]
        if blind_spots:
            blind_bits = [
                _shorten_learning_memory_text(
                    f"{getattr(item, 'tag', '') or '未标注'}错 {item.error_count} 次，最近 {item.last_wrong_at or '未知日期'}，{item.note_count} 篇笔记",
                    48,
                )
                for item in blind_spots
            ]
            blind_section = _build_learning_memory_section("近期高频错题", blind_bits, total_limit=240)
            if blind_section:
                parts.append(blind_section)

        error_lines = _summarize_error_book_groups(get_error_book(db, student_id), limit=5)
        if error_lines:
            error_section = _build_learning_memory_section(
                "代表性错题",
                error_lines,
                numbered=True,
                total_limit=540,
                preserve_items=True,
            )
            if error_section:
                parts.append(error_section)

        note_lines = _summarize_error_review_notes(note_service.list_notes(db, student_id, status="confirmed"), limit=3)
        if note_lines:
            note_section = _build_learning_memory_section(
                "错题复盘笔记", note_lines, numbered=True, total_limit=240, item_limit=90
            )
            if note_section:
                parts.append(note_section)

        if not parts:
            return "\n[学习记忆] 目前错题和复盘笔记数据较少。不要编造历史；可以引导学生上传错题、记录错因或写每日回顾。"

        required = "使用要求：计划、讲题、推荐练习前先参考这些数据；涉及素材细节时先调用 list_materials/read_material；引用时说清依据；没有数据时不要编造；创建学习计划前仍必须先和学生确认"
        prefix = "\n[学习记忆] "
        context = prefix + "；".join([*parts, required]) + "。"
        return context
    except Exception:  # noqa: BLE001
        logger.warning("读取学习记忆失败：student_id=%s", student_id, exc_info=True)
        return ""


def _build_task_context(db: Session, session: Any) -> str:
    """构建 task session 上下文（U-042）。

    注入：稳定画像（学生是谁）+ 当前计划说明 + 任务目标 + 相关知识点。
    不灌全量学习记忆/错题导入（让 AI 按需调用 query_error_book/query_notes 查，省 token）。
    """
    from app.models.p2 import StudyPlan, StudyPlanItem

    parts: list[str] = []
    # 稳定画像（年级/学校/薄弱科目/兴趣），让 AI 知道在跟谁对话
    profile_ctx = _build_profile_context(db, session.student_id)
    if profile_ctx:
        parts.append(profile_ctx)
    plan = db.get(StudyPlan, session.plan_id) if session.plan_id else None
    item = db.get(StudyPlanItem, session.plan_item_id) if session.plan_item_id else None
    if plan:
        # description 优先（U-041），没有退回 focus（兼容旧计划）
        desc = getattr(plan, "description", None) or plan.focus or ""
        if desc:
            parts.append(f"当前学习计划「{plan.title}」说明：{desc}")
        else:
            parts.append(f"当前学习计划「{plan.title}」")
    if item:
        target_line = f"（目标：{item.target}）" if item.target else ""
        parts.append(f"正在做的任务：「{item.title}」{target_line}")
        if item.related_tags:
            parts.append(f"相关知识点：{', '.join(str(t) for t in item.related_tags)}")
    if not parts:
        return ""
    return "\n\n[任务上下文]\n" + "\n".join(parts)


# 冷启动首次引导只问这两项：年级（定难度基线）+ 想提升的科（定方向）。
# 独立于 profile.PROFILE_REQUIRED_FIELDS（后者含 semester/study_preferences，走用时补全）。
COLD_START_FIELDS: tuple[str, ...] = ("grade", "weak_subjects")


def next_cold_start_field(summary: Any) -> str | None:
    """按固定顺序返回下一个要问的冷启动字段；都答完返回 None。

    summary 需有 .summary dict（profile.ProfileSummary 结构）。
    空值（None/""/[]/{}）视为未答。
    """
    data = getattr(summary, "summary", None) or {}
    for field in COLD_START_FIELDS:
        value = data.get(field)
        if value in (None, "", [], {}):
            return field
    return None


def _build_profile_context(
    db: Session, student_id: int, latest_user_content: str = "", mode: str = "study"
) -> str:
    """读学生画像（学习档案+兴趣+近期错因）拼成 system 上下文，让 agent 知道在跟谁对话。

    复用 attribute.get_latest_attributes / interests.list_interests / feedback.list_feedback，不重造。
    无画像时返回空串（不影响 agent 正常工作）。

    M2 D：latest_user_content 非空（用户已提出具体问题）时改用 deferred 冷启动提示，
    不注入「本轮只问」强指令；空消息轮（冷启动自动触发）继续注入 active 硬指令。
    """
    parts: list[str] = []
    is_hobby = mode == "hobby"
    try:
        summary = profile.get_profile_summary(db, student_id)
        next_field = next_cold_start_field(summary) if not is_hobby else None
        if next_field is not None:
            field_label = {"grade": "年级", "weak_subjects": "想提升的科目"}[next_field]
            if (latest_user_content or "").strip():
                parts.append(render("agent/cold_start_deferred", field_label=field_label, next_field=next_field))
            else:
                parts.append(render("agent/cold_start_active", field_label=field_label, next_field=next_field))
        elif summary.needs_onboarding:
            # 冷启动已完成，但学期/偏好仍缺 -> 用时补全，不主动追问
            parts.append(load("agent/cold_start_hint"))
    except Exception:  # noqa: BLE001
        logger.warning("读取冷启动画像摘要失败：student_id=%s", student_id, exc_info=True)
    try:
        attr = attribute.get_latest_attributes(db, student_id)
        if attr and attr.snapshot:
            s = attr.snapshot
            profile_bits = []
            if s.get("grade") or s.get("semester"):
                profile_bits.append(f"当前学段：{s.get('grade', '')}{s.get('semester', '')}".strip())
            if s.get("school"):
                profile_bits.append(f"学校：{s['school']}")
            elif s.get("district"):
                profile_bits.append(f"地区：{s['district']}")
            if not is_hobby and s.get("weak_subjects"):
                profile_bits.append("自认薄弱科目：" + "、".join(str(item) for item in s["weak_subjects"]))
            if not is_hobby and s.get("study_preferences"):
                pref = s["study_preferences"]
                pref_parts = []
                if pref.get("preferred_time"):
                    pref_parts.append(f"偏好时段{pref['preferred_time']}")
                if pref.get("session_minutes"):
                    pref_parts.append(f"单次约{pref['session_minutes']}分钟")
                if pref_parts:
                    profile_bits.append("学习偏好：" + "，".join(pref_parts))
            # M2 C：注入已存教材版本（只作少问一次的复用，不提升为内容证据）；缺失不编默认值
            if not is_hobby and s.get("textbook_versions"):
                versions = s["textbook_versions"]
                if isinstance(versions, dict) and versions:
                    profile_bits.append(
                        "已确认教材版本：" + "；".join(f"{k}={v}" for k, v in versions.items())
                    )
            if profile_bits:
                parts.append("基础画像：" + "；".join(profile_bits))
            subjects = []
            for k, label in settings.config.agent.profile.subject_labels.items():
                if k in s:
                    subjects.append(f"{label}{s[k]}")
            if not is_hobby:
                parts.append(f"学习档案：{', '.join(subjects)}；投入度{s.get('engagement', '?')}；已掌握{s.get('mastered_count', 0)}个知识点")
    except Exception:  # noqa: BLE001  画像读取失败不阻塞对话
        logger.warning("读取学生画像失败：student_id=%s", student_id, exc_info=True)
    try:
        interest_items = interests.list_interests(db, student_id)
        if interest_items:
            approved = [i.tag for i in interest_items if i.approved]
            if approved:
                parts.append(f"已登记兴趣：{', '.join(approved)}")
    except Exception:  # noqa: BLE001
        logger.warning("读取学生兴趣失败：student_id=%s", student_id, exc_info=True)
    try:
        feedback_items = feedback.list_feedback(db, student_id)
        wrong_reasons = [
            _format_wrong_reason_feedback(item.content)
            for item in feedback_items
            if _is_wrong_reason_feedback(item.content, item.feedback_type)
        ][:5]
        if wrong_reasons:
            parts.append("近期错因反馈：" + "；".join(wrong_reasons))
    except Exception:  # noqa: BLE001
        logger.warning("读取学生错因反馈失败：student_id=%s", student_id, exc_info=True)
    try:
        from app.features.note import service as note_service

        notes = note_service.list_notes(db, student_id, status="confirmed")
        daily_reviews = [
            note
            for note in notes
            if note.category == "每日回顾" or note.source == "每日回顾"
        ][:3]
        if daily_reviews:
            review_bits = []
            for note in daily_reviews:
                preview = re.sub(r"^#{1,6}\s*", "", note.content or "", flags=re.MULTILINE)
                preview = re.sub(r"\s+", " ", preview).strip()
                if len(preview) > 120:
                    preview = preview[:120] + "…"
                review_bits.append(f"{note.title}：{preview}")
            parts.append("最近每日回顾：" + "；".join(review_bits))
        if not any(_is_daily_review_for_target_date(note, date.today()) for note in daily_reviews):
            parts.append("今日每日回顾：尚未填写，回答时可以温和提醒学生先补“昨日回顾 + 今日目标”")
    except Exception:  # noqa: BLE001
        logger.warning("读取每日回顾失败：student_id=%s", student_id, exc_info=True)
    if not parts:
        return ""
    return "\n[学生画像] " + "；".join(parts) + "。据此个性化推荐、制定计划和安排同类练习，不用反复问基础信息。"


def _build_daily_learning_record_context(db: Session, student_id: int) -> str:
    """读取每日记录上下文；日报读取失败不能阻塞正常聊天。"""
    try:
        return daily_learning_record_service.build_agent_context(db, student_id)
    except Exception:  # noqa: BLE001 - daily memory is optional context
        logger.warning("读取每日学习记录上下文失败：student_id=%s", student_id, exc_info=True)
        return ""


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    """提取最近一条用户消息文本（去掉 M1 只进 LLM 输入的日期锚点前缀）。

    锚点只应影响 LLM 输入；画像解析/错题路由/空消息判断等服务端逻辑读到原文。
    """
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return strip_current_round_date_anchor(msg["content"])
    return ""


def _latest_error_import_batch_id(messages: list[dict[str, Any]]) -> str | None:
    """从历史对话中提取最近出现的错题导入批次 ID。"""
    patterns = [
        re.compile(r"批次\s*#?\s*(\d+)"),
        re.compile(r"batch[_\s-]?id\s*[=:：#]?\s*(\d+)", re.IGNORECASE),
    ]
    for msg in reversed(messages):
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                return match.group(1)
    return None


def _extract_manual_scores(content: str) -> dict[str, int]:
    """从用户自然语言中提取「第N题X分」形式的老师分数。"""
    scores: dict[str, int] = {}
    pattern = re.compile(r"(?:第\s*)?(\d+)\s*题\s*[：:，,、\s]*(?:得分|分数)?\s*(\d+)\s*分?")
    for match in pattern.finditer(content):
        scores[match.group(1)] = int(match.group(2))
    return scores


def _build_error_import_context(messages: list[dict[str, Any]]) -> str:
    """根据最近消息补充错题导入阶段的路由提示。"""
    latest_user = _latest_user_content(messages)
    batch_id = _latest_error_import_batch_id(messages)
    if not latest_user or not batch_id:
        return ""

    manual_scores = _extract_manual_scores(latest_user)
    if "有分数" in latest_user or manual_scores:
        score_hint = f"；已识别 manual_scores={json.dumps(manual_scores, ensure_ascii=False)}" if manual_scores else ""
        return (
            "\n[错题导入路由提示] "
            f"最近批次 batch_id={batch_id}，用户本轮已经提供老师分数{score_hint}。"
            "本轮必须调用 import_errors_grade，grade_mode=has_score，manual_scores 题号用字符串；禁止再次调用 import_errors_process。"
        )

    if "都没有" in latest_user and ("分数" in latest_user or "答案" in latest_user):
        return (
            "\n[错题导入路由提示] "
            f"最近批次 batch_id={batch_id}，用户本轮表示没有老师分数也没有标准答案。"
            "本轮必须调用 import_errors_grade，grade_mode=no_score_no_answer；禁止再次调用 import_errors_process。"
        )

    if "标准答案" in latest_user or ("答案" in latest_user and "没有" not in latest_user):
        return (
            "\n[错题导入路由提示] "
            f"最近批次 batch_id={batch_id}，用户本轮正在提供标准答案。"
            "收齐答案后应调用 import_errors_grade，grade_mode=no_score_has_answer；不要重复调用 import_errors_process。"
        )

    return ""


def _latest_user_index(messages: list[dict[str, Any]]) -> int:
    """返回最近一条用户消息在消息列表中的位置。"""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return -1


def _has_tool_call_after(messages: list[dict[str, Any]], start_index: int, tool_name: str) -> bool:
    """判断最近用户消息之后是否已经调用过指定工具。"""
    if start_index < 0:
        return False
    for index in range(start_index + 1, len(messages)):
        msg = messages[index]
        if msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            if function.get("name") == tool_name:
                return True
    return False


_LIGHT_PRACTICE_TRIGGER_WORDS = settings.config.agent.light_practice.trigger_keywords
# 轻练内学生明确结束/转正式 → 退出轻练轮（正式动作后 record_feedback 恢复可用）
_LIGHT_PRACTICE_EXIT_WORDS = settings.config.agent.light_practice.exit_keywords


def in_light_practice_round(messages: list[dict[str, Any]]) -> bool:
    """判断当前是否处于轻练轮（最近有轻练意图或判分，且其后无正式退出动作）。

    P2 修复：轻练轮禁止 record_feedback 等落库工具（轻练不沉淀，AI 不把推断当事实）。
    从最近的用户消息向前找轻练触发点（意图词或 grade_light_answer 调用），
    触发点之后若出现正式退出词（做卷子/结束/不练了等）则视为已退出轻练。
    """
    latest_index = _latest_user_index(messages)
    if latest_index < 0:
        return False
    last_light_index = -1
    for i in range(latest_index, -1, -1):
        msg = messages[i]
        content = msg.get("content") or ""
        if msg.get("role") == "user" and isinstance(content, str):
            if any(w in content for w in _LIGHT_PRACTICE_TRIGGER_WORDS):
                last_light_index = i
                break
        elif msg.get("role") == "assistant":
            for tool_call in msg.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                if function.get("name") == "grade_light_answer":
                    last_light_index = i
                    break
            if last_light_index >= 0:
                break
    if last_light_index < 0:
        return False
    # 轻练触发点之后是否有正式退出动作
    for i in range(last_light_index + 1, len(messages)):
        msg = messages[i]
        content = msg.get("content") or ""
        if msg.get("role") == "user" and isinstance(content, str):
            if any(w in content for w in _LIGHT_PRACTICE_EXIT_WORDS):
                return False
    return True


# 试卷路由约束模板（与 agent_loop 强制补调共用同一份，正文在 app/prompts/agent/practice_exam_route.md）
_PRACTICE_EXAM_ROUTE_HINT = load("agent/practice_exam_route")

# 稳定标记：注入时附加在 system 消息末尾，用于判断"已注入过路由约束"。
# 与模板正文解耦——改模板正文不影响已注入检测（P1-2）。
_ROUTE_HINT_INJECTED_MARKER = "[route:create_practice_exam]"


def practice_exam_route_hint(messages: list[dict[str, Any]]) -> str | None:
    """检测高置信「正式试卷」意图，返回应注入的路由约束提示（或 None）。

    修复 P1：轻练会话后发「做一套卷子」被轻练上下文带偏、不调 create_practice_exam。
    只对明确试卷语义（卷子/试卷/套卷/做套题）触发，排除查询语境与随口轻练；
    同一上下文已注入过约束则不重复。
    """
    latest_user = _latest_user_content(messages)
    if not latest_user:
        return None
    # 已注入过路由约束（上一轮已路由）→ 不重复注入；用稳定标记判断，不依赖模板正文
    for msg in reversed(messages):
        content = msg.get("content") or ""
        if isinstance(content, str) and _ROUTE_HINT_INJECTED_MARKER in content:
            return None
        if msg.get("role") == "user" and content:
            break
    # 查询语义排除（看/找/查历史试卷等，不是要出卷）
    if any(w in latest_user for w in settings.config.agent.practice_exam.query_exclusion_keywords):
        return None
    # 随口轻练排除（无试卷语义）
    if any(w in latest_user for w in settings.config.agent.light_practice.trigger_keywords):
        return None
    # 强试卷语义
    if any(w in latest_user for w in settings.config.agent.practice_exam.route_keywords):
        return _PRACTICE_EXAM_ROUTE_HINT
    if re.search(r"(做|出|来)[一套两张三张]*(套题|套卷)", latest_user):
        return _PRACTICE_EXAM_ROUTE_HINT
    return None


def _forced_error_import_tool(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """识别高置信错题导入意图并返回应强制执行的工具调用。"""
    latest_user = _latest_user_content(messages)
    batch_id = _latest_error_import_batch_id(messages)
    latest_index = _latest_user_index(messages)
    if not latest_user or not batch_id:
        return None

    confirmed_homework_review = (
        "逐题作答" in latest_user
        and ("已确认" in latest_user or "刚确认" in latest_user or "基于我" in latest_user)
        and ("批改" in latest_user or "正确答案" in latest_user or "错因" in latest_user)
    )
    if confirmed_homework_review:
        tool_name = "grade_homework_photo"
        if _has_tool_call_after(messages, latest_index, tool_name):
            return None
        return {"name": tool_name, "args": {"batch_id": int(batch_id)}}

    if "[拍题批改]" in latest_user or "拍题批改" in latest_user:
        tool_name = "recognize_homework_photo_markdown"
        if _has_tool_call_after(messages, latest_index, tool_name):
            return None
        return {"name": tool_name, "args": {"batch_id": int(batch_id)}}

    manual_scores = _extract_manual_scores(latest_user)
    if "有分数" in latest_user or manual_scores:
        tool_name = "import_errors_grade"
        if _has_tool_call_after(messages, latest_index, tool_name):
            return None
        args: dict[str, Any] = {"batch_id": int(batch_id), "grade_mode": "has_score"}
        if manual_scores:
            args["manual_scores"] = manual_scores
        return {"name": tool_name, "args": args}

    if "都没有" in latest_user and ("分数" in latest_user or "答案" in latest_user):
        tool_name = "import_errors_grade"
        if _has_tool_call_after(messages, latest_index, tool_name):
            return None
        return {"name": tool_name, "args": {"batch_id": int(batch_id), "grade_mode": "no_score_no_answer"}}

    asks_to_parse = "解析" in latest_user or "识别" in latest_user
    mentions_upload = "已上传" in latest_user or "上传" in latest_user
    if asks_to_parse and mentions_upload:
        tool_name = "import_errors_process"
        if _has_tool_call_after(messages, latest_index, tool_name):
            return None
        return {"name": tool_name, "args": {"batch_id": int(batch_id)}}

    return None


_GRADE_MAP = {
    "一": "一年级",
    "二": "二年级",
    "三": "三年级",
    "四": "四年级",
    "五": "五年级",
    "六": "六年级",
    "七": "七年级",
    "初一": "七年级",
    "八": "八年级",
    "初二": "八年级",
    "九": "九年级",
    "初三": "九年级",
}


def _extract_profile_onboarding_args(text: str, student_id: int) -> dict[str, Any] | None:
    """从高置信冷启动回答中抽取画像参数；只做常见口语兜底，复杂情况交给 LLM 工具。"""
    args: dict[str, Any] = {"student_id": student_id}
    upcoming = re.search(r"开学\s*([一二三四五六七八九]|初一|初二|初三)年级?\s*([上下])?", text)
    current = re.search(r"(?:我是|现在|目前)?\s*([一二三四五六七八九]|初一|初二|初三)年级?\s*([上下])?", text)
    grade_match = upcoming or current
    if grade_match:
        grade_key = grade_match.group(1)
        args["grade"] = _GRADE_MAP.get(grade_key, f"{grade_key}年级")
        term = grade_match.group(2)
        if term:
            args["semester"] = "上册" if term == "上" else "下册"

    weak_subjects: list[str] = []
    for subject in ["语文", "数学", "英语", "物理", "化学"]:
        # 科目后置：数学比较薄弱 / 数学不会
        if re.search(rf"{subject}[^，。；、]*?(?:薄弱|不好|差|弱|不会|不太行|想补|要补|补一?下|加强|提升)", text):
            weak_subjects.append(subject)
        # 科目前置：想先补数学 / 补一下英语 / 重点加强物理（补强词在科目前）
        elif re.search(rf"(?:想补|先补|要补|补一?下|加强|提升)[^，。；、]{{0,8}}?{subject}", text):
            weak_subjects.append(subject)
    if weak_subjects:
        args["weak_subjects"] = weak_subjects

    interest_match = re.search(r"(?:对|喜欢|爱好是|兴趣是)([^，。；、]+?)(?:感兴趣|有兴趣|$|，|。|；)", text)
    if interest_match:
        interest = interest_match.group(1).strip()
        if interest:
            args["add_interests"] = [interest]

    for time_word in ["上午", "中午", "下午", "晚上", "周末"]:
        if time_word in text:
            args["study_preferences"] = {"preferred_time": time_word}
            break

    has_profile_signal = any(key in args for key in ["grade", "weak_subjects", "add_interests", "study_preferences"])
    # student_id 恒在；抽到任一画像字段即应落库（旧 >=3 门槛会让只有 grade 的回答被 weak_subjects 连坐丢弃）
    return args if has_profile_signal and len(args) >= 2 else None


def _latest_profile_question_field(messages: list[dict[str, Any]], latest_user_index: int) -> str | None:
    """找 latest_user 之前最近的 present_profile_question 工具调用，返回其 field。

    chips 回答（点选项）时，field 直接对应学生回答应落库的画像字段。
    """
    for msg in reversed(messages[:latest_user_index]):
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            if func.get("name") != "present_profile_question":
                continue
            try:
                call_args = json.loads(func.get("arguments") or "{}")
            except Exception:  # noqa: BLE001
                continue
            field = call_args.get("field")
            if field:
                return field
    return None


def _forced_profile_onboarding_tool(messages: list[dict[str, Any]], db: Session, student_id: int) -> dict[str, Any] | None:
    """学生回答冷启动问题时，优先增量写入画像，避免绕去查旧档案或只记兴趣。

    兜底针对打字/「回复数字」回答：抽到画像信号就强制调 update_profile（增量、不写反馈）。
    chips 回答由 LLM 自己调 update_profile 驱动，不依赖这里。
    """
    if not student_id:
        return None
    latest_user = _latest_user_content(messages)
    latest_index = _latest_user_index(messages)
    if not latest_user:
        return None
    try:
        summary = profile.get_profile_summary(db, student_id)
    except Exception:  # noqa: BLE001
        logger.warning("读取画像摘要失败，跳过强制画像保存：student_id=%s", student_id, exc_info=True)
        return None
    if not summary.needs_onboarding:
        return None
    # chips 回答确定落库：即使 LLM 调过画像工具但字段仍 missing，强制补（修 grade 漏传丢失）
    pq_field = _latest_profile_question_field(messages, latest_index)
    if pq_field == "grade" and "grade" in summary.missing_fields:
        return {"name": "update_profile", "args": {"student_id": student_id, "grade": _GRADE_MAP.get(latest_user, latest_user)}}
    if pq_field == "weak_subjects" and "weak_subjects" in summary.missing_fields:
        return {"name": "update_profile", "args": {"student_id": student_id, "weak_subjects": [latest_user]}}
    # 打字回答兜底：LLM 已调过画像工具则跳过，避免误存时段/兴趣
    if _has_tool_call_after(messages, latest_index, "update_profile") or _has_tool_call_after(messages, latest_index, "save_profile_onboarding"):
        return None
    args = _extract_profile_onboarding_args(latest_user, student_id)
    if not args:
        return None
    # 首次冷启动只兜底 grade/weak_subjects，避免误存时段/兴趣
    if not {"grade", "weak_subjects"}.intersection(args.keys()):
        return None
    return {"name": "update_profile", "args": args}


def _is_study_plan_confirmed(messages: list[dict[str, Any]]) -> bool:
    """判断最近一轮是否已经从“草案协商”进入“确认创建”。"""
    return validate_study_plan_confirmation(messages).allowed
