from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.p2 import StudentInterest
from .schemas import InterestItem


def add_interest(db: Session, student_id: int, tag: str, source: str = "manual") -> InterestItem:
    clean_tag = tag.strip()[:64]
    if not clean_tag:
        raise ValueError("兴趣标签不能为空")
    approved = source == "manual"  # 学生主动添加直接确认；agent/家长建议等待学生确认
    existing = db.query(StudentInterest).filter(StudentInterest.student_id == student_id, StudentInterest.tag == clean_tag).first()
    if existing:
        if approved and not existing.approved:
            existing.approved = True
            existing.source = source
            db.commit()
            db.refresh(existing)
        return InterestItem(id=existing.id, tag=existing.tag, source=existing.source, approved=existing.approved)
    interest = StudentInterest(student_id=student_id, tag=clean_tag, source=source, approved=approved)
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return InterestItem(id=interest.id, tag=interest.tag, source=interest.source, approved=interest.approved)


def list_interests(db: Session, student_id: int) -> list[InterestItem]:
    items = db.query(StudentInterest).filter(StudentInterest.student_id == student_id).order_by(StudentInterest.approved.desc(), StudentInterest.id.desc()).all()
    return [InterestItem(id=i.id, tag=i.tag, source=i.source, approved=i.approved) for i in items]


def confirm_interest(db: Session, interest_id: int, student_id: int) -> InterestItem | None:
    interest = db.get(StudentInterest, interest_id)
    if not interest or interest.student_id != student_id:
        return None
    interest.approved = True
    db.commit()
    db.refresh(interest)
    return InterestItem(id=interest.id, tag=interest.tag, source=interest.source, approved=interest.approved)


def remove_interest(db: Session, interest_id: int, student_id: int) -> bool:
    interest = db.get(StudentInterest, interest_id)
    if not interest or interest.student_id != student_id:
        return False
    db.delete(interest)
    db.commit()
    return True
