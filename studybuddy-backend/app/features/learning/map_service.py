from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.error_book import ErrorBook
from app.models.material import Material
from app.models.note import Note
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.question import Question
from .schemas.learning_map import LearningMapNode, LearningMapResource, LearningMapResponse, LearningMapStatus


RECENT_WRONG_DAYS = 14
RESOURCE_LIMIT_PER_NODE = 5


@dataclass
class _NodeDraft:
    tag: str
    error_count: int = 0
    note_count: int = 0
    material_count: int = 0
    plan_item_count: int = 0
    last_wrong_at: datetime | None = None
    has_review_note: bool = False
    has_confirmed_material: bool = False
    has_done_plan: bool = False
    has_plan: bool = False
    resources: list[LearningMapResource] = field(default_factory=list)


def build_learning_map(db: Session, student_id: int, limit: int = 30) -> LearningMapResponse:
    drafts: dict[str, _NodeDraft] = {}

    _collect_errors(db, student_id, drafts)
    _collect_notes(db, student_id, drafts)
    _collect_materials(db, student_id, drafts)
    _collect_plan_items(db, student_id, drafts)

    all_nodes = [_to_node(draft) for draft in drafts.values()]
    all_nodes.sort(key=_node_sort_key)

    # summary 基于全量统计（截断前），total_count/has_more 供前端分组折叠与分页
    summary = {"weak": 0, "reviewing": 0, "stable": 0, "unknown": 0}
    for node in all_nodes:
        summary[node.status] = summary.get(node.status, 0) + 1

    nodes = all_nodes[:limit]

    return LearningMapResponse(
        student_id=student_id,
        generated_at=datetime.utcnow().isoformat(),
        nodes=nodes,
        summary=summary,
        total_count=len(all_nodes),
        has_more=len(all_nodes) > limit,
    )


def summarize_learning_map_for_agent(map_data: LearningMapResponse, limit: int = 5) -> list[str]:
    status_text = {
        "weak": "需要优先补",
        "reviewing": "正在巩固",
        "stable": "基本稳定",
        "unknown": "资料已沉淀，掌握度待验证",
    }
    lines: list[str] = []
    for node in map_data.nodes[:limit]:
        label = status_text.get(node.status, node.status)
        counts = f"错题{node.error_count}次，笔记{node.note_count}篇，素材{node.material_count}个，计划{node.plan_item_count}项"
        action = node.next_actions[0] if node.next_actions else "先查看相关记录再决定下一步。"
        lines.append(f"{node.tag}：{label}（{counts}）。建议：{action}")
    return lines


def _collect_errors(db: Session, student_id: int, drafts: dict[str, _NodeDraft]) -> None:
    rows = (
        db.query(ErrorBook, Question)
        .join(Question, Question.id == ErrorBook.question_id)
        .filter(ErrorBook.student_id == student_id)
        .order_by(ErrorBook.last_wrong_at.desc())
        .all()
    )
    for error, question in rows:
        for tag in _clean_tags(error.knowledge_tags or question.knowledge_tags):
            draft = _draft_for(drafts, tag)
            draft.error_count += error.error_count or 1
            if error.last_wrong_at and (draft.last_wrong_at is None or error.last_wrong_at > draft.last_wrong_at):
                draft.last_wrong_at = error.last_wrong_at
            _append_resource(
                draft,
                LearningMapResource(
                    id=int(error.id),
                    title=_compact_text(question.stem, fallback="错题"),
                    type="error",
                    status=f"错 {error.error_count or 1} 次",
                    summary=_compact_text(question.stem, max_length=80),
                ),
            )


def _collect_notes(db: Session, student_id: int, drafts: dict[str, _NodeDraft]) -> None:
    notes = (
        db.query(Note)
        .filter(Note.student_id == student_id, Note.mode == "study")
        .order_by(Note.updated_at.desc(), Note.created_at.desc())
        .all()
    )
    for note in notes:
        for tag in _clean_tags(note.knowledge_tags):
            draft = _draft_for(drafts, tag)
            draft.note_count += 1
            if note.category == "错题复盘" or note.source == "错题讲解":
                draft.has_review_note = True
            _append_resource(
                draft,
                LearningMapResource(
                    id=int(note.id),
                    title=note.title,
                    type="note",
                    status=note.status,
                    summary=_compact_text(note.content, max_length=80),
                ),
            )


def _collect_materials(db: Session, student_id: int, drafts: dict[str, _NodeDraft]) -> None:
    materials = (
        db.query(Material)
        .filter(Material.uploaded_by == student_id, Material.mode == "study")
        .order_by(Material.created_at.desc())
        .all()
    )
    for material in materials:
        if not _is_confirmed_material(material):
            continue
        for tag in _clean_tags(material.knowledge_tags):
            draft = _draft_for(drafts, tag)
            draft.material_count += 1
            draft.has_confirmed_material = True
            _append_resource(
                draft,
                LearningMapResource(
                    id=int(material.id),
                    title=material.name,
                    type="material",
                    status=material.recognition_status,
                    summary=_compact_text(material.summary or material.confirmed_markdown, max_length=80),
                ),
            )


def _collect_plan_items(db: Session, student_id: int, drafts: dict[str, _NodeDraft]) -> None:
    rows = (
        db.query(StudyPlanItem, StudyPlan)
        .join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id)
        .filter(StudyPlan.student_id == student_id, StudyPlan.mode == "study")
        .order_by(StudyPlanItem.created_at.desc())
        .all()
    )
    for item, plan in rows:
        for tag in _clean_tags(item.related_tags):
            draft = _draft_for(drafts, tag)
            draft.plan_item_count += 1
            draft.has_plan = True
            if item.status == "done":
                draft.has_done_plan = True
            _append_resource(
                draft,
                LearningMapResource(
                    id=int(item.id),
                    title=item.title,
                    type="plan_item",
                    status=item.status,
                    summary=_compact_text(item.target or plan.title, max_length=80),
                ),
            )


def _to_node(draft: _NodeDraft) -> LearningMapNode:
    status = _status_for(draft)
    return LearningMapNode(
        tag=draft.tag,
        status=status,
        error_count=draft.error_count,
        note_count=draft.note_count,
        material_count=draft.material_count,
        plan_item_count=draft.plan_item_count,
        last_wrong_at=draft.last_wrong_at.isoformat() if draft.last_wrong_at else None,
        next_actions=_next_actions_for(draft, status),
        resources=draft.resources,
    )


def _status_for(draft: _NodeDraft) -> LearningMapStatus:
    has_recent_wrong = bool(draft.last_wrong_at and draft.last_wrong_at >= datetime.utcnow() - timedelta(days=RECENT_WRONG_DAYS))
    if draft.error_count >= 3 or (has_recent_wrong and not draft.has_review_note):
        return "weak"
    if draft.has_done_plan and not has_recent_wrong:
        return "stable"
    if draft.error_count > 0 and (draft.has_review_note or draft.has_confirmed_material or draft.has_plan):
        return "reviewing"
    if draft.error_count > 0:
        return "weak"
    return "unknown"


def _next_actions_for(draft: _NodeDraft, status: LearningMapStatus) -> list[str]:
    if status == "weak" and not draft.has_review_note:
        return ["先选 1 道错题整理复盘笔记。", "复盘后再做 2 道同类题。"]
    if status == "weak":
        return ["先复看复盘笔记，再做 2 道同类题。"]
    if status == "reviewing" and draft.has_plan and not draft.has_done_plan:
        return ["把未完成的练习任务补完，完成后再复盘。"]
    if status == "reviewing":
        return ["用已有笔记或素材复习一遍，再做一次小练习。"]
    if status == "stable":
        return ["保持复习频率，一周后再抽查。"]
    return ["这部分已有资料，但还缺练习反馈。"]


def _node_sort_key(node: LearningMapNode) -> tuple[int, int, str]:
    status_rank = {"weak": 0, "reviewing": 1, "stable": 2, "unknown": 3}
    activity_score = node.error_count + node.note_count + node.material_count + node.plan_item_count
    return (status_rank.get(node.status, 9), -activity_score, node.tag)


def _draft_for(drafts: dict[str, _NodeDraft], tag: str) -> _NodeDraft:
    if tag not in drafts:
        drafts[tag] = _NodeDraft(tag=tag)
    return drafts[tag]


def _append_resource(draft: _NodeDraft, resource: LearningMapResource) -> None:
    if len([item for item in draft.resources if item.type == resource.type]) >= RESOURCE_LIMIT_PER_NODE:
        return
    draft.resources.append(resource)


def _clean_tags(raw_tags: Any) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw_tags:
        tag = str(value).strip() if value is not None else ""
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
    return cleaned


def _is_confirmed_material(material: Material) -> bool:
    return material.recognition_status == "confirmed" or bool((material.confirmed_markdown or "").strip())


def _compact_text(value: str | None, fallback: str = "", max_length: int = 32) -> str:
    text = " ".join((value or fallback).split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 1]}..."
