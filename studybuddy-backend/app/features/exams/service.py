"""试卷导入与查询服务编排。

注意：options/answer_json/knowledge_tags/match_params 均为 JSON 列，
SQLAlchemy 自动序列化，直接传 Python 对象即可，不要 json.dumps。
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.exam_assignment import ExamAssignment
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.grading_rule import GradingRule
from app.models.question import Question
from app.models.user import User
from .schemas.exam import (
    ExamAssignmentItem,
    ExamAssignmentRequest,
    ExamDetailResponse,
    ExamImportRequest,
    ExamImportResponse,
    ExamListItem,
    ExamStatusRequest,
    QuestionResponse,
    QuestionType,
)
from app.core.auth import access_service


def import_exam(db: Session, req: ExamImportRequest, teacher_id: int, status: str = "draft", *, commit: bool = True) -> ExamImportResponse:
    """导入试卷：建 exam → 逐题建 question + grading_rule → 一次性 commit。"""
    exam = Exam(
        title=req.title,
        subject=req.subject,
        feedback_mode=req.feedback_mode,
        shuffle_groups=req.shuffle_groups,
        status=status,
        created_by=teacher_id,
    )
    db.add(exam)
    db.flush()  # 拿 exam.id

    for q in req.questions:
        question = Question(
            exam_id=exam.id,
            group_id=q.group_id,
            type=q.type.value,
            stem=q.stem,
            options=q.options,  # JSON 列，直接传 list
            answer_json=q.answer,  # JSON 列，直接传
            score=q.score,
            knowledge_tags=q.knowledge_tags,  # JSON 列
        )
        db.add(question)
        db.flush()  # 拿 question.id

        rule = GradingRule(
            question_id=question.id,
            rule_type=q.grading.rule_type,
            matcher=q.grading.matcher,
            match_params=q.grading.match_params,  # JSON 列
        )
        db.add(rule)

    if commit:
        db.commit()
        db.refresh(exam)
    else:
        db.flush()
    return ExamImportResponse(exam_id=exam.id, title=exam.title, question_count=len(req.questions))


def create_practice_exam(db: Session, student_id: int, req: ExamImportRequest, plan_item_id: int | None = None) -> dict:
    """学生自练卷：出卷(published, created_by=student) + 分发给自己 + 关联 plan_item，单事务单 commit。

    不复用 assign_exam（teacher 权限检查不适用学生自练）；plan_item_id 校验归属。
    """
    from app.models.p2 import StudyPlan, StudyPlanItem

    if plan_item_id:
        item = db.get(StudyPlanItem, plan_item_id)
        if not item:
            raise ValueError(f"计划项 {plan_item_id} 不存在")
        plan = db.get(StudyPlan, item.plan_id)
        if not plan or plan.student_id != student_id:
            raise PermissionError("无权操作该计划项")
    result = import_exam(db, req, student_id, status="published", commit=False)
    assignment = ExamAssignment(
        exam_id=result.exam_id,
        student_id=student_id,
        assigned_by=student_id,
        status="assigned",
        plan_item_id=plan_item_id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return {
        "exam_id": result.exam_id,
        "assignment_id": assignment.id,
        "plan_item_id": plan_item_id,
        "title": result.title,
        "question_count": result.question_count,
    }


def _serialize_assignment(assignment: ExamAssignment, student: User | None) -> ExamAssignmentItem:
    return ExamAssignmentItem(
        id=assignment.id,
        exam_id=assignment.exam_id,
        student_id=assignment.student_id,
        student_name=(student.display_name or student.username) if student else str(assignment.student_id),
        status=assignment.status,
        due_at=assignment.due_at.isoformat() if assignment.due_at else None,
        note=assignment.note,
    )


def _serialize_exam_list_item(
    exam: Exam,
    question_count: int,
    total_score: float,
    *,
    visibility: str | None = None,
    assignment: ExamAssignment | None = None,
    latest_record: ExamRecord | None = None,
) -> ExamListItem:
    return ExamListItem(
        id=exam.id,
        title=exam.title,
        subject=exam.subject,
        status=exam.status,
        visibility=visibility,
        assignment_status=assignment.status if assignment else None,
        assignment_note=assignment.note if assignment else None,
        assignment_due_at=(
            assignment.due_at.isoformat() if assignment and assignment.due_at else None
        ),
        question_count=question_count,
        total_score=total_score,
        created_at=exam.created_at.strftime("%Y-%m-%d %H:%M:%S") if exam.created_at else "",
        latest_record_status=latest_record.status if latest_record else None,
        latest_record_id=latest_record.id if latest_record else None,
    )


def _get_active_assignment(db: Session, exam_id: int, student_id: int) -> ExamAssignment | None:
    return (
        db.query(ExamAssignment)
        .filter(
            ExamAssignment.exam_id == exam_id,
            ExamAssignment.student_id == student_id,
            ExamAssignment.status != "cancelled",
        )
        .first()
    )


def _exam_has_any_assignments(db: Session, exam_id: int) -> bool:
    return db.query(ExamAssignment.id).filter(ExamAssignment.exam_id == exam_id).first() is not None


def assign_exam(db: Session, exam_id: int, teacher_id: int, req: ExamAssignmentRequest) -> list[ExamAssignmentItem]:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    if exam.created_by != teacher_id:
        raise PermissionError("无权分发该试卷")

    items: list[ExamAssignmentItem] = []
    for student_id in req.student_ids:
        if not access_service.teacher_can_access_student(db, teacher_id, student_id):
            raise PermissionError(f"学生 {student_id} 未绑定，不能分发试卷")

        assignment = (
            db.query(ExamAssignment)
            .filter(ExamAssignment.exam_id == exam_id, ExamAssignment.student_id == student_id)
            .first()
        )
        if assignment is None:
            assignment = ExamAssignment(
                exam_id=exam_id,
                student_id=student_id,
                assigned_by=teacher_id,
                status="assigned",
            )
            db.add(assignment)

        assignment.assigned_by = teacher_id
        assignment.status = "assigned"
        assignment.due_at = req.due_at
        assignment.note = req.note
        db.flush()

        student = db.get(User, student_id)
        items.append(_serialize_assignment(assignment, student))

    db.commit()
    return items


def list_exam_assignments(db: Session, exam_id: int, teacher_id: int) -> list[ExamAssignmentItem]:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    if exam.created_by != teacher_id:
        raise PermissionError("无权查看该试卷分发")

    assignments = (
        db.query(ExamAssignment)
        .filter(ExamAssignment.exam_id == exam_id)
        .order_by(ExamAssignment.id.asc())
        .all()
    )
    students = {student.id: student for student in db.query(User).filter(User.id.in_([a.student_id for a in assignments])).all()} if assignments else {}
    return [_serialize_assignment(assignment, students.get(assignment.student_id)) for assignment in assignments]


def cancel_exam_assignment(db: Session, exam_id: int, assignment_id: int, teacher_id: int) -> None:
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    if exam.created_by != teacher_id:
        raise PermissionError("无权取消该试卷分发")

    assignment = db.get(ExamAssignment, assignment_id)
    if not assignment or assignment.exam_id != exam_id:
        raise ValueError("分发记录不存在")
    assignment.status = "cancelled"
    db.commit()


def student_can_access_exam(db: Session, exam_id: int, student_id: int) -> bool:
    return _get_active_assignment(db, exam_id, student_id) is not None


def get_exam_detail(db: Session, exam_id: int, user: User) -> ExamDetailResponse:
    """查询试卷详情（★ 不含 answer_json：QuestionResponse 显式不声明该字段）。"""
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    if user.role == "teacher":
        pass
    elif user.role == "student":
        if exam.status != "published":
            raise PermissionError("试卷未发布")
        if not student_can_access_exam(db, exam_id, user.id):
            raise PermissionError("试卷未分发给该学生")
    else:
        raise PermissionError("无权查看试卷")

    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.id).all()
    return ExamDetailResponse(
        id=exam.id,
        title=exam.title,
        feedback_mode=exam.feedback_mode,
        questions=[
            QuestionResponse(
                id=q.id,
                type=QuestionType(q.type),
                stem=q.stem,
                options=q.options,
                score=float(q.score),
                group_id=q.group_id,
            )
            for q in questions
        ],
    )


def list_exams(db: Session, user: User) -> list[ExamListItem]:
    """列出试卷（★ 不含 answer_json）。学生只看自己可访问的 published。"""
    query = db.query(Exam)
    if user.role == "teacher":
        exams = query.order_by(Exam.id.desc()).all()
        active_assignments_by_exam_id: dict[int, ExamAssignment] = {}
        assigned_exam_ids: set[int] = set()
    else:
        exams = query.filter(Exam.status == "published").order_by(Exam.id.desc()).all()
        active_assignments = (
            db.query(ExamAssignment)
            .filter(ExamAssignment.student_id == user.id, ExamAssignment.status != "cancelled")
            .all()
        )
        active_assignments_by_exam_id = {
            assignment.exam_id: assignment for assignment in active_assignments
        }
    # 学生：批量查最新 exam_record，用于列表显示完成状态
    latest_record_by_exam: dict[int, ExamRecord] = {}
    if user.role == "student" and exams:
        records = (
            db.query(ExamRecord)
            .filter(ExamRecord.student_id == user.id, ExamRecord.exam_id.in_([e.id for e in exams]))
            .order_by(ExamRecord.id.desc())
            .all()
        )
        for record in records:
            if record.exam_id not in latest_record_by_exam:
                latest_record_by_exam[record.exam_id] = record
    items: list[ExamListItem] = []
    for exam in exams:
        assignment = active_assignments_by_exam_id.get(exam.id)
        visibility: str | None = None
        if user.role == "student":
            if assignment is not None:
                visibility = "assigned"
            else:
                continue
        questions = db.query(Question).filter(Question.exam_id == exam.id).all()
        total_score = sum(float(q.score) for q in questions)
        items.append(
            _serialize_exam_list_item(
                exam,
                len(questions),
                total_score,
                visibility=visibility,
                assignment=assignment,
                latest_record=latest_record_by_exam.get(exam.id),
            )
        )
    return items


def update_exam_status(db: Session, exam_id: int, req: ExamStatusRequest) -> ExamListItem:
    """发布/归档试卷。"""
    exam = db.get(Exam, exam_id)
    if not exam:
        raise ValueError(f"试卷 {exam_id} 不存在")
    exam.status = req.status
    if req.status == "published" and exam.published_at is None:
        exam.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)

    questions = db.query(Question).filter(Question.exam_id == exam.id).all()
    return _serialize_exam_list_item(exam, len(questions), sum(float(q.score) for q in questions))
