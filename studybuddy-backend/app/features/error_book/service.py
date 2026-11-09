"""错题本服务：写入（upsert_error_book）+ 查询（get_error_book/get_error_book_by_subject）。

读接口原放在 diagnosis_service（learning 域），属错题本读，移入 error_book 与写接口成对
（约束 #6 增内聚），并解决 error_book/router 反向依赖 diagnosis 的问题（§5 单向）。
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.constants import DEFAULT_QUESTION_TYPE_LABEL, QUESTION_TYPE_LABELS
from app.models.answer import Answer
from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.question import Question

from .dedup import error_fingerprint
from .schemas import ErrorGroup, ErrorQuestionItem, ErrorSubjectGroup, ErrorTypeGroup


def upsert_error_book(
    db: Session,
    student_id: int,
    question_id: int,
    exam_record_id: int,
    knowledge_tags: list[str],
) -> None:
    """原子写入或累加错题本同生同题记录。"""
    now = datetime.now(timezone.utc)
    bind = db.get_bind()
    if bind.dialect.name == "mysql":
        stmt = mysql_insert(ErrorBook).values(
            student_id=student_id,
            question_id=question_id,
            exam_record_id=exam_record_id,
            knowledge_tags=knowledge_tags,
            error_count=1,
            last_wrong_at=now,
        )
        stmt = stmt.on_duplicate_key_update(
            exam_record_id=exam_record_id,
            knowledge_tags=knowledge_tags,
            error_count=ErrorBook.__table__.c.error_count + 1,
            last_wrong_at=now,
        )
        db.execute(stmt)
        return

    updated = (
        db.query(ErrorBook)
        .filter(
            ErrorBook.student_id == student_id,
            ErrorBook.question_id == question_id,
        )
        .update(
            {
                ErrorBook.exam_record_id: exam_record_id,
                ErrorBook.knowledge_tags: knowledge_tags,
                ErrorBook.error_count: ErrorBook.error_count + 1,
                ErrorBook.last_wrong_at: now,
            },
            synchronize_session=False,
        )
    )
    if updated:
        return

    db.add(
        ErrorBook(
            student_id=student_id,
            question_id=question_id,
            exam_record_id=exam_record_id,
            knowledge_tags=knowledge_tags,
            error_count=1,
            last_wrong_at=now,
        )
    )


def _load_error_book_context(
    db: Session, student_id: int
) -> tuple[list[ErrorBook], dict[int, Question], dict[int, str]]:
    """加载错题本上下文：ErrorBook 记录 + 关联题目 + 每题最近一次作答。

    get_error_book 和 get_error_book_by_subject 共用，避免重复的批量预取逻辑。
    """
    records = (
        db.query(ErrorBook)
        .filter(ErrorBook.student_id == student_id)
        .order_by(ErrorBook.last_wrong_at.desc())
        .all()
    )
    if not records:
        return [], {}, {}

    question_ids = [eb.question_id for eb in records]
    questions = {q.id: q for q in db.query(Question).filter(Question.id.in_(question_ids)).all()}
    student_record_ids = [
        r.id for r in db.query(ExamRecord.id).filter(ExamRecord.student_id == student_id).all()
    ]
    latest_answer_by_question: dict[int, str] = {}
    if student_record_ids:
        answers = (
            db.query(Answer)
            .filter(
                Answer.exam_record_id.in_(student_record_ids),
                Answer.question_id.in_(question_ids),
            )
            .order_by(Answer.id.desc())
            .all()
        )
        for answer in answers:
            if answer.question_id not in latest_answer_by_question:
                latest_answer_by_question[answer.question_id] = answer.student_answer or ""

    return records, questions, latest_answer_by_question


def get_error_book(db: Session, student_id: int, tag: str | None = None) -> list[ErrorGroup]:
    """错题本：按 tag 分组展示错题。

    口径：以 error_book 表为主（已按 student+question 去重、累加 error_count），
    按 knowledge_tags 展开到 tag 维度分组。
    """
    records, questions, latest_answer_by_question = _load_error_book_context(db, student_id)
    if not records:
        return []

    groups: dict[str, dict[str, Any]] = {}
    for eb in records:
        tags: list[str] = eb.knowledge_tags or []
        question = questions.get(eb.question_id)
        if not question:
            continue
        student_answer = latest_answer_by_question.get(question.id, "")
        correct_answer = str(question.answer_json)

        for t in tags:
            if tag and t != tag:
                continue
            if t not in groups:
                groups[t] = {
                    "tag": t,
                    "error_count": 0,
                    "last_wrong_at": "",
                    "questions": [],
                }
            groups[t]["error_count"] = max(groups[t]["error_count"], eb.error_count)
            last_wrong = eb.last_wrong_at
            groups[t]["last_wrong_at"] = last_wrong.strftime("%Y-%m-%d %H:%M:%S") if last_wrong else ""
            groups[t]["questions"].append(
                ErrorQuestionItem(
                    error_id=eb.id,
                    question_id=question.id,
                    stem=question.stem,
                    student_answer=student_answer or "",
                    correct_answer=correct_answer,
                    error_count=eb.error_count,
                )
            )

    return [ErrorGroup(**g) for g in groups.values()]


def _format_answer(answer_json: Any) -> str:
    """把 answer_json 列（可能是裸值/{'answer':x}/列表）格式化成可读字符串。"""
    if answer_json is None:
        return ""
    if isinstance(answer_json, dict):
        if "answer" in answer_json:
            return _format_answer(answer_json["answer"])
        return "; ".join(f"{k}: {v}" for k, v in answer_json.items())
    if isinstance(answer_json, (list, tuple)):
        return ", ".join(str(x) for x in answer_json)
    return str(answer_json)


def get_error_book_by_subject(db: Session, student_id: int) -> list[ErrorSubjectGroup]:
    """错题本：学科 -> 题型 两级分组（错题本页顶层文件夹用）。

    subject 直接取 exams.subject 原值（如「英语」），前端 SUBJECT_LABELS 命中则转标签、
    否则原样展示，做到数据驱动、不写死学科列表。避免 get_error_book 的循环内查询（N+1）。
    """
    records, questions, latest_by_q = _load_error_book_context(db, student_id)
    if not records:
        return []

    # 额外预取试卷学科映射（subject 分组专用）
    exam_ids = {q.exam_id for q in questions.values()}
    subjects = {e.id: e.subject for e in db.query(Exam).filter(Exam.id.in_(exam_ids)).all()}

    # subject -> question_type -> 分组。组内再按题目指纹合并，避免同题来自多张试卷时重复展示。
    subj_map: dict[str, dict[str, dict[str, Any]]] = {}
    question_map: dict[tuple[str, str, str, str], ErrorQuestionItem] = {}
    for eb in records:
        question = questions.get(eb.question_id)
        if not question:
            continue
        subject = subjects.get(question.exam_id) or "未分类"
        qtype = question.type
        fingerprint = error_fingerprint(subject, qtype, question.stem, question.answer_json)
        type_map = subj_map.setdefault(subject, {})
        if qtype not in type_map:
            type_map[qtype] = {
                "question_type": qtype,
                "type_label": QUESTION_TYPE_LABELS.get(qtype, DEFAULT_QUESTION_TYPE_LABEL),
                "error_count": 0,
                "last_wrong_at": "",
                "questions": [],
            }
        grp = type_map[qtype]
        grp["error_count"] += eb.error_count
        if not grp["last_wrong_at"] and eb.last_wrong_at:
            grp["last_wrong_at"] = eb.last_wrong_at.strftime("%Y-%m-%d %H:%M:%S")
        if fingerprint in question_map:
            existing = question_map[fingerprint]
            existing.error_count += eb.error_count
            if not existing.student_answer and latest_by_q.get(question.id):
                existing.student_answer = latest_by_q[question.id]
            existing.knowledge_tags = sorted(set(existing.knowledge_tags) | {str(t) for t in (eb.knowledge_tags or question.knowledge_tags or [])})
            continue
        item = ErrorQuestionItem(
            error_id=eb.id,
            question_id=question.id,
            stem=question.stem,
            student_answer=latest_by_q.get(question.id, ""),
            correct_answer=_format_answer(question.answer_json),
            error_count=eb.error_count,
            knowledge_tags=[str(t) for t in (eb.knowledge_tags or question.knowledge_tags or [])],
        )
        question_map[fingerprint] = item
        grp["questions"].append(item)

    result: list[ErrorSubjectGroup] = []
    for subject, type_map in subj_map.items():
        type_groups = [ErrorTypeGroup(**g) for g in type_map.values()]
        total = sum(len(g.questions) for g in type_groups)
        result.append(ErrorSubjectGroup(subject=subject, total_count=total, type_groups=type_groups))
    return result
