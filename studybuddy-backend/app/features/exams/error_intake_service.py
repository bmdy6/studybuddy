from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.features.error_book.service import upsert_error_book

__all__ = ["VirtualExamErrorItem", "save_virtual_exam_errors"]


@dataclass
class VirtualExamErrorItem:
    """一条待入错题本的错题（建到虚拟试卷下）。

    判错逻辑、stem 文案、answer_json 结构由调用方决定，本服务只负责建试卷/记录/题目 + 入错题本。
    """

    stem: str
    answer_json: dict[str, Any]
    tags: list[str]


def save_virtual_exam_errors(
    db: Session,
    *,
    student_id: int,
    exam_title: str,
    subject: str,
    error_items: list[VirtualExamErrorItem],
) -> dict[str, Any]:
    """把一批错题建到“虚拟试卷”下并入错题本。

    共享 photo_grading（拍题批改）和 exam_batch（错题导入）两条路径的
    “建虚拟试卷 + ExamRecord + Question + 入错题本”骨架；判错逻辑、stem 格式、
    answer_json 结构由调用方决定后以 ``error_items`` 传入。

    复用规则：
    - 同一 ``exam_title + subject + created_by=1`` 复用虚拟试卷（重复判分不重复造试卷）；
    - 同一 ``exam + student`` 复用 ExamRecord；
    - 同一 ``exam + stem`` 复用 Question（重复判同一题不重复造题）；
    - ``upsert_error_book`` 同生同题唯一，重复判时原子累加。

    返回 ``{"exam_id", "record_id", "saved_count"}``。不置 batch.status、不 commit，
    交由调用方决定（调用方还需补充各自的返回字段）。
    """
    from app.models.exam import Exam
    from app.models.exam_record import ExamRecord
    from app.models.question import Question

    exam = (
        db.query(Exam)
        .filter(Exam.title == exam_title, Exam.subject == subject, Exam.created_by == 1)
        .order_by(Exam.id.desc())
        .first()
    )
    if not exam:
        exam = Exam(title=exam_title, subject=subject, created_by=1, status="published")
        db.add(exam)
        db.flush()

    record = (
        db.query(ExamRecord)
        .filter(ExamRecord.exam_id == exam.id, ExamRecord.student_id == student_id)
        .order_by(ExamRecord.id.desc())
        .first()
    )
    if not record:
        record = ExamRecord(
            exam_id=exam.id,
            student_id=student_id,
            status="graded",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(record)
        db.flush()

    saved_count = 0
    for item in error_items:
        question = (
            db.query(Question)
            .filter(Question.exam_id == exam.id, Question.stem == item.stem)
            .first()
        )
        if not question:
            question = Question(
                exam_id=exam.id,
                type="fill_blank",
                stem=item.stem,
                answer_json=item.answer_json,
                score=100,
                knowledge_tags=item.tags,
            )
            db.add(question)
            db.flush()
        upsert_error_book(db, student_id, question.id, record.id, item.tags)
        saved_count += 1

    return {"exam_id": exam.id, "record_id": record.id, "saved_count": saved_count}
