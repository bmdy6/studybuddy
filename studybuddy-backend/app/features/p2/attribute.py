from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants import ATTRIBUTE_INIT_BASE
from app.models.p2 import StudentAttribute
from .schemas import AttributeSnapshot, InitAttributesRequest

# 能力项科目（与雷达图一致）。subject_sources 只对这些 key 记录证据来源。
ATTRIBUTE_SUBJECTS = ("chinese", "math", "english", "pe", "engagement")
# 证据来源标记：exam_score=大考录入，manual_adjust=agent 微调。未标记视为无证据。
SUBJECT_SOURCE_EXAM = "exam_score"
SUBJECT_SOURCE_MANUAL = "manual_adjust"


def _score_to_attr(exam_score: int) -> int:
    """大考成绩(0-100)折算属性值：基准 60 + 偏移。"""
    # 成绩 60->60, 80->75, 100->100 的线性映射
    return min(100, max(ATTRIBUTE_INIT_BASE, int(ATTRIBUTE_INIT_BASE + (exam_score - 60) * 1.0)))


def init_attributes(db: Session, student_id: int, exam_scores: dict[str, int]) -> AttributeSnapshot:
    """初始化属性：录入大考成绩折算。

    只为真实录入的考试科目（chinese/math/english/pe）标记 exam_score 证据并写入折算分；
    未录入考试科目不写假 60 占位分，也不标记证据来源（前端展示「数据不足」）。
    engagement 作为综合学习投入估算值保留初始 50，但不标记为考试证据。
    """
    snapshot: dict[str, Any] = {"engagement": 50, "mastered_count": 0}
    subject_sources: dict[str, str] = {}
    for subject, score in exam_scores.items():
        if subject not in ATTRIBUTE_SUBJECTS:
            continue
        try:
            raw = int(score)
        except (TypeError, ValueError):
            continue
        snapshot[subject] = _score_to_attr(raw)
        subject_sources[subject] = SUBJECT_SOURCE_EXAM
    snapshot["subject_sources"] = subject_sources
    attr = StudentAttribute(student_id=student_id, snapshot=snapshot, source="init")
    db.add(attr)
    db.commit()
    db.refresh(attr)
    return AttributeSnapshot(
        id=attr.id,
        snapshot=attr.snapshot,
        source=attr.source,
        trigger_ref=attr.trigger_ref,
        created_at=attr.created_at.strftime("%Y-%m-%d %H:%M:%S") if attr.created_at else "",
    )


def _normalize_snapshot_sources(snapshot: dict[str, Any]) -> dict[str, Any]:
    """读取兼容：旧快照没有 subject_sources 字段时，保守推断为无证据（空 dict）。

    旧 init 全 60 数据没有证据标记，不恢复默认 60 作为真实分；前端据 subject_sources
    判断每个能力项是否有真实来源。返回的是 snapshot 的副本，不改动入库数据。
    """
    if "subject_sources" in snapshot:
        return snapshot
    normalized = dict(snapshot)
    normalized["subject_sources"] = {}
    return normalized


def get_latest_attributes(db: Session, student_id: int) -> AttributeSnapshot | None:
    """获取最新属性快照。旧快照无 subject_sources 时保守补空（无证据）。"""
    attr = db.query(StudentAttribute).filter(StudentAttribute.student_id == student_id).order_by(StudentAttribute.id.desc()).first()
    if not attr:
        return None
    return AttributeSnapshot(
        id=attr.id,
        snapshot=_normalize_snapshot_sources(attr.snapshot),
        source=attr.source,
        trigger_ref=attr.trigger_ref,
        created_at=attr.created_at.strftime("%Y-%m-%d %H:%M:%S") if attr.created_at else "",
    )


def get_attribute_history(db: Session, student_id: int) -> list[AttributeSnapshot]:
    """获取属性历史快照（成长曲线）。每条快照都带 subject_sources 供前端判断证据。"""
    items = db.query(StudentAttribute).filter(StudentAttribute.student_id == student_id).order_by(StudentAttribute.id).all()
    return [
        AttributeSnapshot(
            id=a.id,
            snapshot=_normalize_snapshot_sources(a.snapshot),
            source=a.source,
            trigger_ref=a.trigger_ref,
            created_at=a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else "",
        )
        for a in items
    ]


def update_attributes(db: Session, student_id: int, delta: dict[str, int], reason: str | None = None) -> AttributeSnapshot:
    """基于最新快照叠加增量调整，新建一条快照（保留成长历史）。

    delta: {chinese:+5, mastered_count:+1, ...} 只传要改的字段，增量可负。
    被微调的能力项科目标记 manual_adjust（覆盖原 exam_score）；未触及科目保留原证据来源。
    无历史快照时不以全 60 基准起步伪造能力分，只为被触及的能力项科目从中性基准起算并标记 manual_adjust。
    """
    latest = db.query(StudentAttribute).filter(StudentAttribute.student_id == student_id).order_by(StudentAttribute.id.desc()).first()
    if latest:
        base = _normalize_snapshot_sources(latest.snapshot)
    else:
        # 无历史：不写全 60 假能力分，只承载被微调字段与必要元数据
        base = {"mastered_count": 0, "subject_sources": {}}
    sources = dict(base.get("subject_sources") or {})
    for key, value in delta.items():
        if key not in ATTRIBUTE_SUBJECTS and key != "mastered_count":
            continue
        previous = base.get(key)
        if previous is None:
            # 无历史基准时，被微调能力项从中性基准起算（60 为折算基准，非伪造真实分）
            new_value = ATTRIBUTE_INIT_BASE + int(value) if key in ATTRIBUTE_SUBJECTS else int(value)
        else:
            new_value = int(previous) + int(value)
        base[key] = max(0, min(100, new_value)) if key in ATTRIBUTE_SUBJECTS else max(0, new_value)
        if key in ATTRIBUTE_SUBJECTS:
            sources[key] = SUBJECT_SOURCE_MANUAL
    base["subject_sources"] = sources
    attr = StudentAttribute(
        student_id=student_id,
        snapshot=base,
        source="manual",
        trigger_ref=(reason[:64] if reason else None),
    )
    db.add(attr)
    db.commit()
    db.refresh(attr)
    return AttributeSnapshot(
        id=attr.id,
        snapshot=attr.snapshot,
        source=attr.source,
        trigger_ref=attr.trigger_ref,
        created_at=attr.created_at.strftime("%Y-%m-%d %H:%M:%S") if attr.created_at else "",
    )
