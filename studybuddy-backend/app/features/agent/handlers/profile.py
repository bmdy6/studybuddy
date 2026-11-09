"""Agent 学生画像/属性/兴趣工具处理器。

拆自 app/core/agent_loop.py。get_attributes/init_attributes/record_interest/update_attributes
画像查询与调整、save_profile_onboarding/update_profile/present_profile_question 冷启动画像采集。
依赖方向：单向依赖 context（_resolve_tool_student_id）+ features.p2（同层业务）。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.features.p2 import attribute, interests, profile
from app.features.p2.schemas import ProfileOnboardingRequest, UpdateProfileRequest
from ..context import _resolve_tool_student_id


async def _handle_get_attributes(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """获取学习档案。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    latest = attribute.get_latest_attributes(db, sid)
    if not latest:
        return {"message": "学习档案尚未初始化，请先录入大考成绩初始化"}
    return {"current": latest.model_dump()}


async def _handle_save_profile_onboarding(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """保存冷启动学习画像：对话里收齐基础信息后直接落库，不要求先有大考成绩。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    req = ProfileOnboardingRequest(
        grade=args.get("grade"),
        semester=args.get("semester"),
        school=args.get("school"),
        district=args.get("district"),
        textbook_versions=args.get("textbook_versions") or {},
        recent_scores=args.get("recent_scores") or {},
        weak_subjects=args.get("weak_subjects") or [],
        study_preferences=args.get("study_preferences") or {},
        interests=args.get("interests") or [],
    )
    summary = profile.save_profile_onboarding(db, sid, req, actor_role=role)
    return {
        "id": sid,
        "saved": True,
        "summary": summary.model_dump(),
        "message": "已补全冷启动学习画像",
        "next_step": "不要再次调用 save_profile_onboarding，直接用自然语言确认已保存的信息并询问下一步学习安排。",
    }


async def _handle_update_profile(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """对话中学到明确事实时静默增量更新画像：只覆盖传入字段，不写反馈，不碰能力分证据。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    req = UpdateProfileRequest(
        grade=args.get("grade"),
        semester=args.get("semester"),
        school=args.get("school"),
        district=args.get("district"),
        textbook_versions=args.get("textbook_versions") or {},
        recent_scores=args.get("recent_scores") or {},
        weak_subjects=args.get("weak_subjects") or [],
        study_preferences=args.get("study_preferences") or {},
        add_interests=args.get("add_interests") or [],
        remove_interests=args.get("remove_interests") or [],
    )
    summary = profile.update_profile(db, sid, req, actor_role=role)
    return {
        "id": sid,
        "updated": True,
        "summary": summary.model_dump(),
        "message": "已更新画像",
        "next_step": "不要重复调用 update_profile；用自然语言复述已更新信息或继续补下一个缺失字段。",
    }


async def _handle_present_profile_question(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """展示型工具：把画像问题+选项交给前端渲染成 chips。不做落库，只回显供 agent 组织提问文本。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    field = args.get("field") or ""
    question = args.get("question") or ""
    options = args.get("options") or []
    allow_other = bool(args.get("allow_other"))
    return {
        "asked": True,
        "field": field,
        "question": question,
        "options": options,
        "allow_other": allow_other,
        "next_step": "下一轮只输出问题文本、不再调工具，等学生点选项或回复；收到答案后用 update_profile 落库。",
    }


async def _handle_init_attributes(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """初始化学习档案：仅家长可用。"""
    if role != "teacher":
        raise PermissionError("只有家长能初始化属性")
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    attr = attribute.init_attributes(db, sid, args["exam_scores"])
    return {"id": attr.id, "snapshot": attr.snapshot, "initialized": True}


async def _handle_record_interest(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """记录学生兴趣：agent 在对话中发现稳定兴趣时调用。两角色都可（student 记自己的）。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    tag = args.get("tag", "").strip()
    if not tag:
        return {"error": "缺少兴趣标签 tag"}
    item = interests.add_interest(db, sid, tag, source="inferred")  # inferred 等学生确认/移除
    return {
        "id": item.id,
        "tag": item.tag,
        "saved": True,
        "summary": f"已记录兴趣「{tag}」（待学生确认）",
    }


async def _handle_update_attributes(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """微调学习档案：agent 基于对话/做题反馈小幅调整属性，新建快照保留历史。两角色都可。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    delta = args.get("delta") or {}
    if not delta:
        return {"error": "缺少调整内容 delta"}
    # 只允许已知字段
    allowed = {"chinese", "math", "english", "pe", "engagement", "mastered_count"}
    clean_delta = {k: int(v) for k, v in delta.items() if k in allowed}
    if not clean_delta:
        return {"error": f"delta 无有效字段，允许：{allowed}"}
    reason = args.get("reason")
    attr = attribute.update_attributes(db, sid, clean_delta, reason)
    changes = ", ".join(f"{k}{'+' if v >= 0 else ''}{v}" for k, v in clean_delta.items())
    return {
        "id": attr.id,
        "snapshot": attr.snapshot,
        "updated": True,
        "summary": f"已更新学习档案（{changes}）",
    }
