"""统一记忆召回：FTS(LIKE) + 标签 + 时效 混合打分，k=8"""
import re
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.note import Note
from app.models.error_book import ErrorBook
from app.models.p2 import StudyPlanItem, StudyPlan
from app.models.material import Material

def _tag_overlap(query_tags: set[str], item_tags: list[str]) -> float:
    if not query_tags or not item_tags:
        return 0.0
    return len(query_tags & set(item_tags)) / max(len(query_tags), 1)

def _fts_score(query: str, text: str) -> float:
    if not query or not text:
        return 0.0
    # 简版：LIKE 命中 1.0，否则 0
    return 1.0 if query.lower() in text.lower() else 0.0

def _recency_score(dt) -> float:
    if not dt:
        return 0.0
    try:
        # naive UTC 视作 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - dt).days
        return max(0.0, 1.0 - days / 30.0)
    except Exception:
        return 0.0

def search_workspace_memory(db: Session, student_id: int, query: str, mode: str = "study", k: int = 8):
    q = (query or "").strip()
    q_tags = set(re.split(r"[\s,，]+", q)) if q else set()
    hits = []
    # notes
    for n in db.query(Note).filter(Note.student_id == student_id, Note.status == "confirmed").limit(50).all():
        text = f"{n.title or ''} {n.content or ''} {' '.join(n.knowledge_tags or [])}"
        score = 0.5 * _tag_overlap(q_tags, n.knowledge_tags or []) + 0.3 * _fts_score(q, text) + 0.2 * _recency_score(getattr(n, "updated_at", None) or getattr(n, "created_at", None))
        if score > 0:
            hits.append({"type": "note", "id": n.id, "title": n.title or "", "snippet": (n.content or "")[:80], "score": score, "source": "note"})
    # error_book
    for e in db.query(ErrorBook).filter(ErrorBook.student_id == student_id).limit(50).all():
        text = " ".join(e.knowledge_tags or [])
        score = 0.5 * _tag_overlap(q_tags, e.knowledge_tags or []) + 0.3 * _fts_score(q, text) + 0.2 * _recency_score(getattr(e, "last_wrong_at", None))
        if score > 0:
            hits.append({"type": "error_book", "id": e.id, "title": "错题", "snippet": text[:80], "score": score, "source": "error_book"})
    # study_plan_items active
    for item in db.query(StudyPlanItem).join(StudyPlan, StudyPlan.id == StudyPlanItem.plan_id).filter(StudyPlan.student_id == student_id, StudyPlan.status == "active").limit(50).all():
        text = f"{item.title or ''} {' '.join(item.related_tags or [])}"
        score = 0.5 * _tag_overlap(q_tags, item.related_tags or []) + 0.3 * _fts_score(q, text) + 0.2 * _recency_score(getattr(item, "created_at", None))
        if score > 0:
            hits.append({"type": "study_plan_item", "id": item.id, "title": item.title or "", "snippet": text[:80], "score": score, "source": "study_plan"})
    # materials
    for m in db.query(Material).filter(Material.student_id == student_id).limit(20).all():
        text = f"{m.name or ''} {m.recognized_markdown or ''}"
        score = 0.3 * _fts_score(q, text) + 0.2 * _recency_score(getattr(m, "recognized_at", None))
        if score > 0:
            hits.append({"type": "material", "id": m.id, "title": m.name or "", "snippet": text[:80], "score": score, "source": "material"})
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:k]
