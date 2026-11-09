"""答题提交与判分编排服务。

关键：ORM Question/GradingRule 模型已满足 core/grading.py 的 Protocol 类型
（score/answer_json 与 rule_type/matcher/match_params），可直接传给 grade()，
无需计划中的 duck-typing Q/R 临时类。JSON 列已是 Python 对象，不要 json.loads。
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.constants import MANUAL_PASS_THRESHOLD
from app.core.grading import GradeResult, _normalize_choice_answer, _normalize_choice_display, grade
from app.models.answer import Answer
from app.models.exam import Exam
from app.models.exam_assignment import ExamAssignment
from app.models.exam_record import ExamRecord
from app.models.grading_rule import GradingRule
from app.models.question import Question
from app.models.user import User
from .schemas.answer import (
    ExamRecordAnswerResult,
    ExamRecordResult,
    GradeManualRequest,
    GradeManualResponse,
    PendingGradeItem,
    StartExamResponse,
    SubmitRequest,
    SubmitResponse,
)
from app.core.auth import access_service
from app.features.error_book.service import upsert_error_book
from .service import student_can_access_exam

# MVP-B 防敷衍门禁阈值（多信号，避免单一用时误伤认真学生）
MIN_VALID_ANSWER_RATIO = 0.5  # 非空答案占比低于 50% 视为敷衍
MIN_SECONDS_PER_QUESTION = 15  # 每客观题最少用时（秒），低于视为乱点


def _assess_quality(req: SubmitRequest, record: ExamRecord, answered_count: int) -> bool:
    """整卷质量评估：疑似敷衍/乱点返回 True（跳过写错题本）。"""
    # 信号1：非空答案占比（主判据）
    if req.answers:
        blank = sum(1 for a in req.answers if not (a.student_answer or '').strip())
        if blank / len(req.answers) > (1 - MIN_VALID_ANSWER_RATIO):
            return True
    # 信号2：客观题用时下限（辅助判据，主观题卷不判用时）
    if answered_count > 0 and record.started_at:
        # MySQL DATETIME 无时区（naive），用 naive UTC now 比较
        now_naive = datetime.utcnow()
        started = record.started_at
        if started.tzinfo is not None:
            started = started.replace(tzinfo=None)
        elapsed = (now_naive - started).total_seconds()
        if elapsed < MIN_SECONDS_PER_QUESTION * answered_count:
            return True
    return False


def start_exam(db: Session, exam_id: int, student_id: int) -> StartExamResponse:
    """学生开始考试：创建 ExamRecord。"""
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    if exam.status != "published":
        raise ValueError("试卷未发布，不能开始作答")
    if not student_can_access_exam(db, exam_id, student_id):
        raise PermissionError("试卷未分发给该学生")

    latest_record = (
        db.query(ExamRecord)
        .filter(
            ExamRecord.exam_id == exam_id,
            ExamRecord.student_id == student_id,
        )
        .order_by(ExamRecord.id.desc())
        .first()
    )
    if latest_record is not None and latest_record.status == "in_progress":
        return StartExamResponse(
            exam_record_id=latest_record.id,
            exam_id=exam_id,
            status=latest_record.status,
        )

    record = ExamRecord(
        exam_id=exam_id,
        student_id=student_id,
        status="in_progress",
    )
    db.add(record)
    assignment = (
        db.query(ExamAssignment)
        .filter(
            ExamAssignment.exam_id == exam_id,
            ExamAssignment.student_id == student_id,
            ExamAssignment.status == "assigned",
        )
        .first()
    )
    if assignment is not None:
        assignment.status = "started"
    db.commit()
    db.refresh(record)
    return StartExamResponse(exam_record_id=record.id, exam_id=exam_id, status=record.status)


def submit_exam(db: Session, exam_id: int, req: SubmitRequest, student_id: int) -> SubmitResponse:
    """交卷：逐题判分 → 写 answer → 客观题错则记错题本。"""
    record = db.get(ExamRecord, req.exam_record_id)
    if not record or record.student_id != student_id:
        raise ValueError("考试记录不存在或不属于该学生")
    if record.exam_id != exam_id:
        raise ValueError("考试记录不属于该试卷")
    if record.status != "in_progress":
        raise ValueError("考试记录状态不允许提交")

    seen_question_ids: set[int] = set()
    objective_score = 0.0
    pending_manual = 0

    # MVP-B：先评估整卷质量（空答案占比/用时），疑似敷衍则跳过写错题本
    answered_count = sum(1 for a in req.answers if (a.student_answer or '').strip())
    low_quality = _assess_quality(req, record, answered_count)

    for ans in req.answers:
        question = db.get(Question, ans.question_id)
        if not question:
            raise ValueError(f"题目 {ans.question_id} 不存在")
        if question.exam_id != record.exam_id:
            raise ValueError(f"题目 {ans.question_id} 不属于当前试卷")
        if question.id in seen_question_ids:
            raise ValueError(f"题目 {ans.question_id} 重复提交")
        seen_question_ids.add(question.id)
        rule = db.query(GradingRule).filter(GradingRule.question_id == question.id).first()

        if rule is None:
            # 无判分规则 → 标记待人工批改
            result = GradeResult(0, None, "无判分规则，待人工批改", needs_manual=True)
        else:
            result = grade(ans.student_answer, question, rule)

        answer = Answer(
            exam_record_id=record.id,
            question_id=question.id,
            student_answer=ans.student_answer,
            score=result.score,
            is_correct=int(result.is_correct) if result.is_correct is not None else None,
            is_manual_graded=1 if result.needs_manual else 0,
            graded_at=datetime.now(timezone.utc) if not result.needs_manual else None,
        )
        db.add(answer)

        if result.needs_manual:
            pending_manual += 1
        else:
            objective_score += result.score
            if result.is_correct is False and not low_quality:
                _save_error_book(db, student_id, question, record.id)

    record.status = "submitted"
    record.submitted_at = datetime.now(timezone.utc)
    record.total_score = Decimal(str(objective_score))
    record.suspected_low_quality = 1 if low_quality else 0
    assignment = (
        db.query(ExamAssignment)
        .filter(
            ExamAssignment.exam_id == exam_id,
            ExamAssignment.student_id == student_id,
            ExamAssignment.status != "cancelled",
        )
        .first()
    )
    if assignment is not None:
        assignment.status = "submitted"
    db.commit()

    return SubmitResponse(
        exam_record_id=record.id,
        status="submitted",
        objective_score=objective_score,
        pending_manual_count=pending_manual,
    )


def _save_error_book(db: Session, student_id: int, question: Question, record_id: int) -> None:
    """记录/累加错题本（同一学生+题目唯一）。"""
    tags = [str(tag) for tag in (question.knowledge_tags or [])]
    upsert_error_book(db, student_id, question.id, record_id, tags)


def cleanup_stale_exam_records(db: Session, older_than_hours: int = 24, limit: int = 100) -> tuple[int, list[int]]:
    """清理过期空考试记录：只删除无作答的 in_progress 空壳。"""
    cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
    has_answer = db.query(Answer.id).filter(Answer.exam_record_id == ExamRecord.id).exists()
    records = (
        db.query(ExamRecord)
        .filter(
            ExamRecord.status == "in_progress",
            ExamRecord.started_at < cutoff,
            ~has_answer,
        )
        .order_by(ExamRecord.started_at.asc(), ExamRecord.id.asc())
        .limit(limit)
        .all()
    )
    ids = [record.id for record in records]
    for record in records:
        db.delete(record)
    db.commit()
    return len(ids), ids


def get_exam_record_result(db: Session, record_id: int, user: User) -> ExamRecordResult:
    """查询考试记录结果；按 feedback_mode 控制是否下发答案和对错。"""
    record = db.get(ExamRecord, record_id)
    if not record:
        raise ValueError("考试记录不存在")
    if user.role == "student" and record.student_id != user.id:
        raise PermissionError("只能查看自己的考试结果")
    if user.role == "teacher" and not access_service.teacher_can_access_student(db, user.id, record.student_id):
        raise PermissionError("无权查看该学生考试结果")
    if user.role not in {"student", "teacher"}:
        raise PermissionError("无权查看考试结果")

    exam = db.get(Exam, record.exam_id)
    if not exam:
        raise ValueError("试卷不存在")

    hide_feedback = exam.feedback_mode == "hidden"
    answers = (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .filter(Answer.exam_record_id == record.id)
        .order_by(Question.id.asc())
        .all()
    )

    items: list[ExamRecordAnswerResult] = []
    for answer in answers:
        question = db.get(Question, answer.question_id)
        if not question:
            continue
        is_correct = None if answer.is_correct is None else bool(answer.is_correct)
        correct_answer = None if hide_feedback else _display_answer(question)
        items.append(
            ExamRecordAnswerResult(
                answer_id=answer.id,
                question_id=question.id,
                question_stem=question.stem,
                question_type=question.type,
                student_answer=answer.student_answer or "",
                correct_answer=correct_answer,
                is_correct=None if hide_feedback else is_correct,
                score=None if hide_feedback or answer.score is None else float(answer.score),
                max_score=float(question.score),
                graded=answer.is_correct is not None,
                knowledge_tags=[str(tag) for tag in (question.knowledge_tags or [])],
            )
        )

    return ExamRecordResult(
        exam_record_id=record.id,
        exam_id=record.exam_id,
        exam_title=exam.title,
        status=record.status,
        total_score=None if hide_feedback or record.total_score is None else float(record.total_score),
        feedback_mode=exam.feedback_mode,
        answers=items,
    )


def list_pending_grades(db: Session, limit: int = 20) -> list[PendingGradeItem]:
    """列出待人工批改的作答。"""
    answers = (
        db.query(Answer)
        .filter(
            Answer.is_manual_graded == 1,
            Answer.manual_score.is_(None),
        )
        .order_by(Answer.id)
        .limit(limit)
        .all()
    )

    items: list[PendingGradeItem] = []
    for a in answers:
        record = db.get(ExamRecord, a.exam_record_id)
        if not record:
            continue
        student = db.get(User, record.student_id)
        exam = db.get(Exam, record.exam_id)
        question = db.get(Question, a.question_id)
        if not (student and exam and question):
            continue
        items.append(
            PendingGradeItem(
                answer_id=a.id,
                exam_record_id=record.id,
                student_name=student.display_name or student.username,
                exam_title=exam.title,
                question_id=question.id,
                question_stem=question.stem,
                question_type=question.type,
                max_score=float(question.score),
                student_answer=a.student_answer or "",
                reference_answer=str(question.answer_json),
                submitted_at=record.submitted_at.isoformat() if record.submitted_at else "",
            )
        )
    return items


def grade_manually(db: Session, answer_id: int, req: GradeManualRequest) -> GradeManualResponse:
    """人工批改回填：更新 answer.score/is_correct，错则记错题本，全部判完则置 graded。"""
    answer = db.get(Answer, answer_id)
    if not answer:
        raise ValueError("作答不存在")

    question = db.get(Question, answer.question_id)
    if not question:
        raise ValueError("题目不存在")

    max_score = float(question.score)
    is_correct = req.manual_score >= max_score * MANUAL_PASS_THRESHOLD

    score_decimal = Decimal(str(req.manual_score))
    answer.manual_score = score_decimal
    answer.manual_comment = req.manual_comment
    answer.score = score_decimal
    answer.is_correct = int(is_correct)
    answer.is_manual_graded = 1
    answer.graded_at = datetime.now(timezone.utc)

    if not is_correct:
        record = db.get(ExamRecord, answer.exam_record_id)
        if record and not record.suspected_low_quality:
            _save_error_book(db, record.student_id, question, record.id)

    # 检查该考试记录是否全部判完
    record = db.get(ExamRecord, answer.exam_record_id)
    if record:
        pending = (
            db.query(Answer)
            .filter(
                Answer.exam_record_id == record.id,
                Answer.is_manual_graded == 1,
                Answer.manual_score.is_(None),
            )
            .count()
        )
        if pending == 0:
            record.status = "graded"

    db.commit()

    return GradeManualResponse(
        answer_id=answer.id,
        graded=True,
        score=float(answer.score) if answer.score is not None else 0.0,
        is_correct=bool(answer.is_correct),
        graded_at=answer.graded_at.isoformat() if answer.graded_at else "",
    )


def recalculate_submitted_records(db: Session, apply: bool = True) -> tuple[int, int]:
    """修复协议错误的历史判分（P0）：用当前 grade()（normalize 索引/字母）重算 submitted 记录的客观题。

    历史 AI 自练卷 correct_answer 存数字索引，旧判分比较失败导致正式 0 分；
    grade() 已归一化，对存量数据重算。返回 (受影响 records 数, 受影响 answers 数)。
    apply=False 为 dry-run（只统计不更新）。
    """
    changed_records = 0
    changed_answers = 0
    records = db.query(ExamRecord).filter(ExamRecord.status == "submitted").all()
    for record in records:
        objective_score = 0
        rec_changed = False
        answers = db.query(Answer).filter(Answer.exam_record_id == record.id).all()
        for answer in answers:
            question = db.get(Question, answer.question_id)
            if not question:
                continue
            rule = db.query(GradingRule).filter(GradingRule.question_id == question.id).first()
            if rule is None or rule.rule_type == "manual":
                continue
            result = grade(answer.student_answer, question, rule)
            new_score = result.score
            new_correct = int(result.is_correct) if result.is_correct is not None else None
            if new_score != answer.score or new_correct != answer.is_correct:
                if apply:
                    answer.score = new_score
                    answer.is_correct = new_correct
                changed_answers += 1
                rec_changed = True
            objective_score += new_score
        if rec_changed:
            if apply:
                record.total_score = Decimal(str(objective_score))
            changed_records += 1
    if apply:
        db.commit()
    return changed_records, changed_answers


def _display_answer(question: Question) -> str:
    """结果页正确答案显示（P0 显示协议修复）：选择题 answer_json 数字索引归一化为字母（[2]->C）；
    选项文本内容（如 "went"）保持原样，不再被大写改写（判分与展示解耦，P1 修复）。"""
    raw = question.answer_json
    if question.type in ("single_choice", "multi_choice") and question.options:
        return _normalize_choice_display(raw, len(question.options))
    return str(raw)
