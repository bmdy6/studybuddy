"""p2 画像：冷启动画像补全与对话中增量更新。

聚合属性快照 + 兴趣，不引入新的记忆表（复用 StudentAttribute snapshot）。
依赖方向（单向 #1）：profile -> interests, attribute（仅此两个子模块）。

_sanitizers（_clean_string_list/_clean_text）为通用输入清洗，与 recommendation
模块的同名私有助手各自保留一份：避免 profile 为 8 行通用函数引入对 recommendation
的依赖（耦合面最小，#5 依赖稳定模块、#6 先内聚再解耦）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.p2 import StudentAttribute, StudentInterest
from .attribute import get_latest_attributes
from .interests import add_interest, list_interests
from .schemas import ProfileOnboardingRequest, ProfileSummary, UpdateProfileRequest

# 冷启动完成判定：只要求冷启动实际问的字段（年级 + 薄弱科目）。
# 学期/学习偏好等不在冷启动范围内，不要求（否则冷启动完成后 needs_onboarding 永远 true，微信引导判定异常）。
PROFILE_REQUIRED_FIELDS = ("grade", "weak_subjects")


def _clean_string_list(values: list[str] | None, limit: int = 20) -> list[str]:
    clean: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in clean:
            clean.append(item[:64])
        if len(clean) >= limit:
            break
    return clean


def _clean_text(value: str | None, max_len: int = 80) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text[:max_len] if text else None


def _latest_snapshot_dict(db: Session, student_id: int) -> dict[str, Any]:
    latest = get_latest_attributes(db, student_id)
    return dict(latest.snapshot) if latest and latest.snapshot else {}


def _profile_missing_fields(summary: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in PROFILE_REQUIRED_FIELDS:
        value = summary.get(field)
        if value in (None, "", [], {}):
            missing.append(field)
    return missing


def get_profile_summary(db: Session, student_id: int) -> ProfileSummary:
    """聚合学生冷启动画像摘要；老用户也通过缺失字段自然触发补全。"""
    snapshot = _latest_snapshot_dict(db, student_id)
    interests = [item.tag for item in list_interests(db, student_id) if item.approved]
    summary = {
        "grade": snapshot.get("grade"),
        "semester": snapshot.get("semester"),
        "school": snapshot.get("school"),
        "district": snapshot.get("district"),
        "textbook_versions": snapshot.get("textbook_versions") or {},
        "recent_scores": snapshot.get("recent_scores") or {},
        "weak_subjects": snapshot.get("weak_subjects") or [],
        "study_preferences": snapshot.get("study_preferences") or {},
        "interests": interests,
    }
    missing = _profile_missing_fields(summary)
    return ProfileSummary(student_id=student_id, needs_onboarding=bool(missing), missing_fields=missing, summary=summary)


def save_profile_onboarding(db: Session, student_id: int, req: ProfileOnboardingRequest, actor_role: str) -> ProfileSummary:
    """保存冷启动画像，复用属性快照/兴趣/反馈，不引入新的记忆表。

    冷启动画像补全只记录年级/学期/学校/偏好等画像信息，不产生能力分证据：
    不写入 chinese/math/english/pe/engagement 等能力分，subject_sources 保持为空。
    """
    snapshot = _latest_snapshot_dict(db, student_id)
    # 保留已有能力分与证据来源（若学生已录入大考成绩），但不补默认 60
    updates = {
        "grade": _clean_text(req.grade, 20),
        "semester": _clean_text(req.semester, 20),
        "school": _clean_text(req.school, 120),
        "district": _clean_text(req.district, 80),
    }
    for key, value in updates.items():
        if value:
            snapshot[key] = value
    if req.textbook_versions:
        # M2 C：按科目 merge，不能新增语文版本时覆盖已存英语版本
        merged = dict(snapshot.get("textbook_versions") or {})
        for k, v in req.textbook_versions.items():
            key = str(k).strip()[:32]
            value = str(v).strip()[:64]
            if key and value:
                merged[key] = value
        snapshot["textbook_versions"] = merged
    if req.recent_scores:
        snapshot["recent_scores"] = {str(k).strip()[:32]: max(0, min(100, int(v))) for k, v in req.recent_scores.items() if str(k).strip()}
    weak_subjects = _clean_string_list(req.weak_subjects, limit=10)
    if weak_subjects:
        snapshot["weak_subjects"] = weak_subjects
    if req.study_preferences:
        snapshot["study_preferences"] = req.study_preferences
    # 确保能力分证据来源存在但不补默认分；onboarding 不产生能力分证据
    snapshot.setdefault("subject_sources", {})
    snapshot.setdefault("mastered_count", 0)
    attr = StudentAttribute(student_id=student_id, snapshot=snapshot, source="manual")
    db.add(attr)
    db.commit()

    source = "manual" if actor_role == "student" else "inferred"
    for tag in _clean_string_list(req.interests, limit=20):
        add_interest(db, student_id, tag, source)
    return get_profile_summary(db, student_id)


def update_profile(db: Session, student_id: int, req: UpdateProfileRequest, actor_role: str) -> ProfileSummary:
    """对话中学到明确事实时静默增量更新画像。

    只覆盖传入的非空字段（增量、幂等）；兴趣按增删处理（add 走 add_interest 自动去重，remove 按 tag 删）。
    不写学习反馈（避免重复调用堆积重复反馈），不触碰能力分与 subject_sources 证据。
    返回最新画像摘要，让 agent 看到当前状态以决定是否继续补全。
    """
    snapshot = _latest_snapshot_dict(db, student_id)
    updates = {
        "grade": _clean_text(req.grade, 20),
        "semester": _clean_text(req.semester, 20),
        "school": _clean_text(req.school, 120),
        "district": _clean_text(req.district, 80),
    }
    for key, value in updates.items():
        if value:
            snapshot[key] = value
    if req.textbook_versions:
        # M2 C：按科目 merge，不能新增语文版本时覆盖已存英语版本
        merged = dict(snapshot.get("textbook_versions") or {})
        for k, v in req.textbook_versions.items():
            key = str(k).strip()[:32]
            value = str(v).strip()[:64]
            if key and value:
                merged[key] = value
        snapshot["textbook_versions"] = merged
    if req.recent_scores:
        snapshot["recent_scores"] = {str(k).strip()[:32]: max(0, min(100, int(v))) for k, v in req.recent_scores.items() if str(k).strip()}
    weak_subjects = _clean_string_list(req.weak_subjects, limit=10)
    if weak_subjects:
        snapshot["weak_subjects"] = weak_subjects
    if req.study_preferences:
        snapshot["study_preferences"] = req.study_preferences
    # 不补默认能力分；onboarding/更新都不产生能力分证据
    snapshot.setdefault("subject_sources", {})
    snapshot.setdefault("mastered_count", 0)
    attr = StudentAttribute(student_id=student_id, snapshot=snapshot, source="manual")
    db.add(attr)
    db.commit()

    source = "manual" if actor_role == "student" else "inferred"
    for tag in _clean_string_list(req.add_interests, limit=20):
        add_interest(db, student_id, tag, source)
    for tag in _clean_string_list(req.remove_interests, limit=20):
        clean_tag = tag.strip()[:64]
        if not clean_tag:
            continue
        existing = db.query(StudentInterest).filter(StudentInterest.student_id == student_id, StudentInterest.tag == clean_tag).first()
        if existing:
            db.delete(existing)
    db.commit()
    return get_profile_summary(db, student_id)
