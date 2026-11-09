"""笔记服务：学习记录 CRUD + 盲区聚合。

两层结构（模仿用户 Obsidian 知识库，适配初中生）：
- study_record：学习记录，弟弟学完知识点后 AI 帮整理（概念卡 concept 已废弃，统一学习记录）
- 盲区：不存表，从 error_book 聚合 error_count>=2 的知识点，关联笔记数
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.error_book import ErrorBook
from app.models.note import Note
from .schemas import BlindSpotItem, NoteItem


def _to_item(n: Note) -> NoteItem:
    return NoteItem(
        id=n.id,
        student_id=n.student_id,
        type=n.type,
        title=n.title,
        subject=n.subject,
        category=n.category,
        content=n.content,
        knowledge_tags=n.knowledge_tags or [],
        source=n.source,
        source_ref=n.source_ref or [],
        status=n.status,
        created_at=n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else "",
        updated_at=n.updated_at.strftime("%Y-%m-%d %H:%M:%S") if n.updated_at else "",
    )


def create_note(db: Session, data: dict[str, Any], mode: str = "study") -> NoteItem:
    """创建笔记（agent save_note 工具调）。

    type 统一 study_record（概念卡 concept 已废弃：纯模板空洞，不如让 agent 整理成完整学习记录）。
    category 为学科下的细分分类（如 词汇/语法/阅读），由 agent 保存时判断。
    """
    note = Note(
        student_id=data["student_id"],
        type="study_record",
        title=data["title"],
        subject=data.get("subject", "其他"),
        content=data.get("content", ""),
        knowledge_tags=data.get("knowledge_tags", []),
        source=data.get("source", "其他"),
        source_ref=data.get("source_ref", []),
        category=data.get("category"),
        status=data.get("status", "draft"),  # Agent 默认为草稿；学生手写内容可直接 confirmed
        mode=mode,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _to_item(note)


def list_notes(
    db: Session,
    student_id: int,
    subject: str | None = None,
    note_type: str | None = None,
    status: str | None = None,
    mode: str = "study",
) -> list[NoteItem]:
    """列笔记：按学科/类型/状态过滤，按更新时间倒序。

    status=None 列全部（前端 NotesPage 要显示待确认草稿）；
    AI 查询/记忆注入/家长推送传 status="confirmed" 只看真实笔记。
    """
    query = db.query(Note).filter(Note.student_id == student_id, Note.mode == mode)
    if subject:
        query = query.filter(Note.subject == subject)
    if note_type:
        query = query.filter(Note.type == note_type)
    if status:
        query = query.filter(Note.status == status)
    return [_to_item(n) for n in query.order_by(Note.updated_at.desc()).all()]


def confirm_all_draft_notes(db: Session) -> int:
    """一次性把所有 draft 笔记置 confirmed。

    历史 save_note 直接落 draft 但没有对话确认环节，存量 draft 实为用户已认可的笔记；
    引入「对话确认才转 confirmed」后，用此函数把存量 draft 一次性转 confirmed，
    让它们进 AI 记忆/每日记录/笔记列表（不再显示待确认）。返回迁移条数。
    """
    drafts = db.query(Note).filter(Note.status == "draft").all()
    for note in drafts:
        note.status = "confirmed"
    db.commit()
    return len(drafts)


def get_note(db: Session, note_id: int) -> NoteItem | None:
    n = db.get(Note, note_id)
    return _to_item(n) if n else None


def update_note(db: Session, note_id: int, data: dict[str, Any]) -> NoteItem | None:
    """更新笔记（弟弟编辑/确认）。只更新非 None 字段。"""
    n = db.get(Note, note_id)
    if not n:
        return None
    if data.get("title") is not None:
        n.title = data["title"]
    if data.get("content") is not None:
        n.content = data["content"]
    if data.get("knowledge_tags") is not None:
        n.knowledge_tags = data["knowledge_tags"]
    if data.get("category") is not None:
        n.category = data["category"]
    if data.get("status") is not None:
        n.status = data["status"]
    db.commit()
    db.refresh(n)
    return _to_item(n)


def delete_note(db: Session, note_id: int) -> bool:
    n = db.get(Note, note_id)
    if not n:
        return False
    db.delete(n)
    db.commit()
    return True


def get_blind_spots(db: Session, student_id: int, min_errors: int = 2) -> list[BlindSpotItem]:
    """盲区聚合：从 error_book 找 error_count >= min_errors 的知识点，关联笔记数。

    这是用户 Obsidian 结构里"盲区指针层"的弟弟版——跨错题聚合反复错的点，
    并关联该知识点有多少篇笔记（有笔记说明已学过但仍错，需重点复习）。
    """
    # 从 error_book 聚合：按 knowledge_tags 展开后统计每个 tag 的 error_count
    records = db.query(ErrorBook).filter(ErrorBook.student_id == student_id).all()
    tag_stats: dict[str, dict] = {}  # tag -> {error_count, last_wrong_at}
    for r in records:
        tags = r.knowledge_tags or []
        for t in tags:
            if t not in tag_stats:
                tag_stats[t] = {"error_count": 0, "last_wrong_at": r.last_wrong_at}
            tag_stats[t]["error_count"] += r.error_count
            if r.last_wrong_at and (t not in tag_stats or r.last_wrong_at > tag_stats[t]["last_wrong_at"]):
                tag_stats[t]["last_wrong_at"] = r.last_wrong_at

    # 过滤 + 关联笔记数
    notes = db.query(Note).filter(Note.student_id == student_id).all()
    note_tags: dict[str, int] = {}  # tag -> 笔记数
    for n in notes:
        for t in n.knowledge_tags or []:
            note_tags[t] = note_tags.get(t, 0) + 1

    blind_spots = []
    for tag, stats in tag_stats.items():
        if stats["error_count"] >= min_errors:
            blind_spots.append(
                BlindSpotItem(
                    tag=tag,
                    error_count=stats["error_count"],
                    last_wrong_at=stats["last_wrong_at"].strftime("%Y-%m-%d") if stats["last_wrong_at"] else "",
                    note_count=note_tags.get(tag, 0),
                )
            )
    # 按错题数倒序
    blind_spots.sort(key=lambda x: x.error_count, reverse=True)
    return blind_spots


def get_related_errors(db: Session, note: Note, limit: int = 5) -> list[dict]:
    """查笔记关联的错题：按 knowledge_tags 匹配 error_book，关联 Question 拿题干。

    用于笔记详情页展示「关联错题」——弟弟能看到这个知识点错过哪些题。
    """
    tags = note.knowledge_tags or []
    if not tags:
        return []
    records = (
        db.query(ErrorBook)
        .filter(
            ErrorBook.student_id == note.student_id,
        )
        .all()
    )
    # 按 tag 匹配 + 关联题干
    from app.models.question import Question

    related = []
    seen_qids = set()
    for r in records:
        r_tags = r.knowledge_tags or []
        if not set(tags) & set(r_tags):
            continue
        if r.question_id in seen_qids:
            continue
        seen_qids.add(r.question_id)
        q = db.get(Question, r.question_id)
        related.append(
            {
                "error_id": r.id,
                "question_id": r.question_id,
                "stem": (q.stem[:80] if q else "") if q else "",
                "error_count": r.error_count,
                "last_wrong_at": r.last_wrong_at.strftime("%Y-%m-%d") if r.last_wrong_at else "",
            }
        )
        if len(related) >= limit:
            break
    return related
