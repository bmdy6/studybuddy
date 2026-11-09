from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.p2 import LearningFeedback
from .schemas import FeedbackItem


def submit_feedback(db: Session, student_id: int, feedback_type: str, content: str, related_resource_id: int | None = None) -> FeedbackItem:
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("反馈内容不能为空")
    fb = LearningFeedback(
        student_id=student_id,
        feedback_type=feedback_type,
        content=clean_content,
        related_resource_id=related_resource_id,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return FeedbackItem(
        id=fb.id,
        feedback_type=fb.feedback_type,
        content=fb.content,
        created_at=fb.created_at.strftime("%Y-%m-%d %H:%M:%S") if fb.created_at else "",
    )


def list_feedback(db: Session, student_id: int) -> list[FeedbackItem]:
    items = db.query(LearningFeedback).filter(LearningFeedback.student_id == student_id).order_by(LearningFeedback.id.desc()).limit(50).all()
    return [
        FeedbackItem(
            id=f.id, feedback_type=f.feedback_type, content=f.content, created_at=f.created_at.strftime("%Y-%m-%d %H:%M:%S") if f.created_at else ""
        )
        for f in items
    ]
