"""学习诊断服务：按 tag 聚合错题率，区分 weak/mastered。

错题本读接口（get_error_book / get_error_book_by_subject）已移入
``app.features.error_book.service``（约束 #6 增内聚，与 upsert 写接口成对），
本文件只留诊断聚合。

★ MySQL 5.7 不支持 JSON_TABLE（计划中的 SQL 无法运行），改用 Python 端展开
  knowledge_tags JSON 列做聚合，结果等价且版本无关。
"""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.constants import DIAGNOSIS_TOP_N, MASTERED_THRESHOLD
from app.models.answer import Answer
from app.models.exam_record import ExamRecord
from app.models.question import Question
from app.models.user import User

from .schemas.diagnosis import DiagnosisResponse, WeakPoint


def _aggregate_rows(
    rows: list[tuple[Answer, Question, int]],
) -> dict[int, dict[str, dict[str, int]]]:
    """按 student 分组聚合 tag 统计（供单查/批查共用）。"""
    tag_stats_by_student: dict[int, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0, "wrong": 0})
    )
    for ans, question, student_id in rows:
        tags = question.knowledge_tags or []
        for tag in tags:
            stats = tag_stats_by_student[student_id][tag]
            stats["total"] += 1
            if ans.is_correct is not None and ans.is_correct == 0:
                stats["wrong"] += 1
    return tag_stats_by_student


def _build_response(
    student: User, tag_stats: dict[str, dict[str, int]], top_n: int
) -> DiagnosisResponse:
    weak_points: list[WeakPoint] = []
    mastered_tags: list[str] = []
    # 按 wrong_count 降序取 top_n
    for tag in sorted(tag_stats, key=lambda t: tag_stats[t]["wrong"], reverse=True)[:top_n]:
        stats = tag_stats[tag]
        total = stats["total"]
        wrong = stats["wrong"]
        error_rate = round(wrong / total, 2) if total else 0.0
        mastered = (1 - error_rate) >= MASTERED_THRESHOLD
        wp = WeakPoint(
            tag=tag,
            wrong_count=wrong,
            error_rate=error_rate,
            total_attempts=total,
            mastered=mastered,
        )
        if mastered:
            mastered_tags.append(wp.tag)
        else:
            weak_points.append(wp)

    return DiagnosisResponse(
        student_id=student.id,
        student_name=student.display_name or student.username,
        weak_points=weak_points,
        mastered_tags=mastered_tags,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def get_diagnosis(db: Session, student_id: int, top_n: int = DIAGNOSIS_TOP_N) -> DiagnosisResponse:
    """诊断：按 tag 聚合错题率，区分 weak/mastered。

    统计口径：以 answers 表为主，逐题按 knowledge_tags 展开 tag，
    wrong_count = is_correct=0 的次数，total_attempts = 该 tag 全部作答次数。
    """
    student = db.get(User, student_id)
    if not student:
        raise ValueError(f"学生 {student_id} 不存在")

    rows = (
        db.query(Answer, Question, ExamRecord.student_id)
        .join(Question, Answer.question_id == Question.id)
        .join(ExamRecord, Answer.exam_record_id == ExamRecord.id)
        .filter(ExamRecord.student_id == student_id)
        .all()
    )

    tag_stats = _aggregate_rows(rows)[student_id]
    return _build_response(student, tag_stats, top_n)


def get_diagnoses(
    db: Session, student_ids: list[int], top_n: int = DIAGNOSIS_TOP_N
) -> list[DiagnosisResponse]:
    """批量诊断：一次批拉所有学生的作答数据，避免 N+1 查询放大。

    与 get_diagnosis 单查结果等价，仅查询次数从 2×N 降到固定 3 次。
    """
    if not student_ids:
        return []

    students = (
        db.query(User).filter(User.id.in_(student_ids), User.role == "student").all()
    )
    by_id = {s.id: s for s in students}
    rows = (
        db.query(Answer, Question, ExamRecord.student_id)
        .join(Question, Answer.question_id == Question.id)
        .join(ExamRecord, Answer.exam_record_id == ExamRecord.id)
        .filter(ExamRecord.student_id.in_(student_ids))
        .all()
    )

    tag_stats_by_student = _aggregate_rows(rows)
    return [
        _build_response(by_id[sid], tag_stats_by_student.get(sid, {}), top_n)
        for sid in student_ids
        if sid in by_id
    ]
