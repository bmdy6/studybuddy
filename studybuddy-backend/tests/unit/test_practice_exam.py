"""U-045 学生自练卷单测。

覆盖 _handle_create_practice_exam：
- 出卷 + 自动分发给自己 + 关联 plan_item（同事务）
- 纯自练（无 plan_item）
- 非学生角色拒绝
- plan_item 归属校验
- 格式校验
"""

import asyncio

import pytest

from app.models.exam import Exam
from app.models.exam_assignment import ExamAssignment
from app.models.p2 import StudyPlan, StudyPlanItem
from app.models.question import Question
from app.models.user import User
from app.features.agent.handlers.exam import (
    _handle_create_practice_exam,
    _handle_query_practice_exam_result,
)
from app.features.exams.grading_service import start_exam, submit_exam
from app.features.exams.schemas.answer import AnswerSubmit, SubmitRequest
from app.utils.security import hash_password


VALID_PRACTICE_EXAM = {
    "schema_version": 1,
    "title": "一般过去时自练",
    "subject": "english",
    "feedback_mode": "immediate",
    "questions": [
        {
            "type": "single_choice",
            "stem": "He ___ to school.",
            "options": ["go", "goes", "went", "gone"],
            "answer": "went",
            "score": 2,
            "knowledge_tags": ["过去时"],
            "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
        },
    ],
}


def _make_student(db, username="practice-student") -> User:
    student = User(
        username=username,
        password_hash=hash_password("x"),
        role="student",
        display_name=username,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _make_plan_item(db, student_id):
    plan = StudyPlan(student_id=student_id, title="英语时态", focus="一般过去时")
    db.add(plan)
    db.commit()
    db.refresh(plan)
    item = StudyPlanItem(plan_id=plan.id, title="做时态练习", target="做一套自练卷", minutes=15)
    db.add(item)
    db.commit()
    db.refresh(item)
    return plan, item


class TestCreatePracticeExam:
    def test_student_creates_practice_exam_with_plan_item(self, db):
        """学生为计划项出自练卷 -> 出卷(published) + 分发给自己 + 关联 plan_item，同事务。"""
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["exam_id"] > 0
        assert result["assignment_id"] > 0
        assert result["plan_item_id"] == item.id
        assert result["question_count"] == 1
        # 卷子已发布，创建者是学生
        exam = db.get(Exam, result["exam_id"])
        assert exam.status == "published"
        assert exam.created_by == student.id
        # 分发给自己 + 关联 plan_item
        assignment = db.query(ExamAssignment).filter_by(exam_id=result["exam_id"]).first()
        assert assignment is not None
        assert assignment.student_id == student.id
        assert assignment.assigned_by == student.id
        assert assignment.plan_item_id == item.id
        assert assignment.status == "assigned"

    def test_student_creates_practice_exam_without_plan_item(self, db):
        """纯自练不绑计划项 -> plan_item_id 为 None，仍出卷+分发。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_create_practice_exam(
                VALID_PRACTICE_EXAM,
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert result["plan_item_id"] is None
        assignment = db.query(ExamAssignment).filter_by(exam_id=result["exam_id"]).first()
        assert assignment.plan_item_id is None
        assert assignment.student_id == student.id

    def test_practice_exam_defaults_feedback_mode_immediate(self, db):
        """P2-2：AI 未传 feedback_mode 时默认 immediate（做完一题立即对错），与工具描述/prompt 一致。"""
        student = _make_student(db)
        args = {k: v for k, v in VALID_PRACTICE_EXAM.items() if k != "feedback_mode"}
        result = asyncio.run(
            _handle_create_practice_exam(args, role="student", db=db, teacher_id=student.id)
        )
        assert result["exam_id"] > 0
        exam = db.get(Exam, result["exam_id"])
        assert exam.feedback_mode == "immediate"

    def test_teacher_cannot_create_practice_exam(self, db):
        """非学生角色调自练卷 -> PermissionError。"""
        with pytest.raises(PermissionError):
            asyncio.run(
                _handle_create_practice_exam(
                    VALID_PRACTICE_EXAM,
                    role="teacher",
                    db=db,
                    teacher_id=1,
                )
            )

    def test_student_cannot_use_others_plan_item(self, db):
        """学生用别人的计划项出自练卷 -> 返回 error，不创建卷子。"""
        student = _make_student(db)
        other = _make_student(db, username="other-student")
        _, item = _make_plan_item(db, other.id)
        exam_count_before = db.query(Exam).count()
        result = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert "error" in result
        assert "无权" in result["error"]
        # 本次越权调用不应新增卷子；测试库可能已有其他用例或验收数据。
        assert db.query(Exam).count() == exam_count_before

    def test_nonexistent_plan_item(self, db):
        """plan_item 不存在 -> 返回 error。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "plan_item_id": 999999},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert "error" in result
        assert "不存在" in result["error"]

    def test_query_latest_submitted_result_by_plan_item(self, db):
        student = _make_student(db, username="practice-result-student")
        _, item = _make_plan_item(db, student.id)
        created = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        exam = db.get(Exam, created["exam_id"])
        record = start_exam(db, exam.id, student.id)
        question = db.query(Question).filter(Question.exam_id == exam.id).one()
        submit_exam(
            db,
            exam.id,
            SubmitRequest(
                exam_record_id=record.exam_record_id,
                answers=[AnswerSubmit(question_id=question.id, student_answer="went")],
            ),
            student.id,
        )

        result = asyncio.run(
            _handle_query_practice_exam_result(
                {"plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )

        assert result["exam_id"] == exam.id
        assert result["exam_record_id"] == record.exam_record_id
        assert result["plan_item_id"] == item.id
        assert result["answers"][0]["student_answer"] == "went"
        assert result["answers"][0]["correct_answer"] == "went"
        assert result["answers"][0]["is_correct"] is True

    def test_query_skips_newer_unsubmitted_exam_for_same_plan_item(self, db):
        student = _make_student(db, username="practice-result-order-student")
        _, item = _make_plan_item(db, student.id)
        submitted = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        submitted_exam = db.get(Exam, submitted["exam_id"])
        submitted_record = start_exam(db, submitted_exam.id, student.id)
        submitted_question = db.query(Question).filter(Question.exam_id == submitted_exam.id).one()
        submit_exam(
            db,
            submitted_exam.id,
            SubmitRequest(
                exam_record_id=submitted_record.exam_record_id,
                answers=[AnswerSubmit(question_id=submitted_question.id, student_answer="went")],
            ),
            student.id,
        )
        asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "title": "新卷未提交", "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )

        result = asyncio.run(
            _handle_query_practice_exam_result(
                {"plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )

        assert result["exam_id"] == submitted_exam.id
        assert result["exam_record_id"] == submitted_record.exam_record_id

    def test_hidden_feedback_does_not_report_unknown_answers_as_wrong(self, db):
        student = _make_student(db, username="practice-hidden-student")
        _, item = _make_plan_item(db, student.id)
        created = asyncio.run(
            _handle_create_practice_exam(
                {**VALID_PRACTICE_EXAM, "feedback_mode": "hidden", "plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        exam = db.get(Exam, created["exam_id"])
        record = start_exam(db, exam.id, student.id)
        question = db.query(Question).filter(Question.exam_id == exam.id).one()
        submit_exam(
            db,
            exam.id,
            SubmitRequest(
                exam_record_id=record.exam_record_id,
                answers=[AnswerSubmit(question_id=question.id, student_answer="went")],
            ),
            student.id,
        )

        result = asyncio.run(
            _handle_query_practice_exam_result(
                {"plan_item_id": item.id},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )

        assert result["feedback_mode"] == "hidden"
        assert result["correct_count"] is None
        assert result["graded_count"] == 0
        assert result["pending_count"] == 1
        assert "0/1 题正确" not in result["summary"]

    def test_invalid_exam_format(self, db):
        """试卷格式不合法（缺 questions）-> 返回 error。"""
        student = _make_student(db)
        result = asyncio.run(
            _handle_create_practice_exam(
                {"title": "缺题"},
                role="student",
                db=db,
                teacher_id=student.id,
            )
        )
        assert "error" in result
        assert "格式不合法" in result["error"]
