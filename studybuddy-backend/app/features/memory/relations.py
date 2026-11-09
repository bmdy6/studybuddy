from sqlalchemy.orm import Session
from app.models.memory_relation import MemoryRelation

def create_relations(db: Session, student_id: int, items: list[dict]) -> list[MemoryRelation]:
    rows = []
    for it in items:
        rows.append(MemoryRelation(
            student_id=student_id,
            source_type=it["source_type"],
            source_id=it["source_id"],
            target_type=it["target_type"],
            target_id=it["target_id"],
            relation=it.get("relation", "related_to"),
        ))
    if rows:
        db.add_all(rows)
        db.commit()
        for r in rows:
            db.refresh(r)
    return rows

def list_relations(db: Session, student_id: int, source_type: str | None = None, source_id: int | None = None):
    q = db.query(MemoryRelation).filter(MemoryRelation.student_id == student_id)
    if source_type:
        q = q.filter(MemoryRelation.source_type == source_type)
    if source_id:
        q = q.filter(MemoryRelation.source_id == source_id)
    return q.order_by(MemoryRelation.id.desc()).limit(20).all()
