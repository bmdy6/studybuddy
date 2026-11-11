"""合并历史重复错题。

默认 dry-run，只打印会合并的重复组；加 --apply 才会更新 error_count 并删除重复 error_book 行。
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.question import Question
from app.features.error_book.dedup import error_fingerprint


def _build_groups(db: Session) -> dict[tuple[int, str, str, str, str], list[ErrorBook]]:
    records = db.query(ErrorBook).order_by(ErrorBook.student_id, ErrorBook.last_wrong_at.desc(), ErrorBook.id).all()
    if not records:
        return {}

    question_ids = [r.question_id for r in records]
    questions = {q.id: q for q in db.query(Question).filter(Question.id.in_(question_ids)).all()}
    exam_ids = {q.exam_id for q in questions.values()}
    subjects = {e.id: e.subject for e in db.query(Exam).filter(Exam.id.in_(exam_ids)).all()}

    groups: dict[tuple[int, str, str, str, str], list[ErrorBook]] = defaultdict(list)
    for record in records:
        question = questions.get(record.question_id)
        if not question:
            continue
        subject = subjects.get(question.exam_id) or "未分类"
        groups[(record.student_id, *error_fingerprint(subject, question.type, question.stem, question.answer_json))].append(record)
    return groups


def dedupe_error_book(apply: bool = False) -> int:
    db = SessionLocal()
    try:
        duplicate_groups = {key: rows for key, rows in _build_groups(db).items() if len(rows) > 1}
        for key, rows in duplicate_groups.items():
            canonical = rows[0]
            duplicates = rows[1:]
            total_count = sum(row.error_count for row in rows)
            latest = max((row.last_wrong_at for row in rows if row.last_wrong_at), default=canonical.last_wrong_at)
            print(f"student={key[0]} fingerprint={key[1:]} rows={len(rows)} total_count={total_count} keep={canonical.id}")
            if not apply:
                continue
            canonical.error_count = total_count
            canonical.last_wrong_at = latest
            for duplicate in duplicates:
                db.delete(duplicate)
        if apply:
            db.commit()
        else:
            db.rollback()
        return len(duplicate_groups)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行合并；默认只预览")
    args = parser.parse_args()
    count = dedupe_error_book(apply=args.apply)
    action = "merged" if args.apply else "found"
    print(f"{action} duplicate groups: {count}")
