"""U-044 任务完成判定单测。

覆盖 _handle_complete_task_item：
- passed -> item done + completed_at + 写 attempt
- needs_retry -> item 留 todo 重做 + 写 attempt
- blocked -> item in_progress + 写 attempt
- 无效 assessment / 无权 -> 返回 error
"""

import asyncio

import pytest

from app.models.p2 import StudyPlan, StudyPlanItem, StudyPlanItemAttempt
from app.models.user import User
from app.features.agent.handlers.learning import _handle_complete_task_item
from app.utils.security import hash_password


def _make_student(db, username="completion-student") -> User:
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
    item = StudyPlanItem(plan_id=plan.id, title="复盘错题", target="说出2个错因", minutes=15)
    db.add(item)
    db.commit()
    db.refresh(item)
    return plan, item


class TestCompleteTaskItem:
    def test_passed_marks_done_and_writes_attempt(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "passed",
                    "reason": "说出了2个错因",
                    "evidence_summary": "时态错误+主谓不一致",
                    "confidence": 0.8,
                },
                "student",
                db,
                student.id,
            )
        )
        assert result["assessment"] == "passed"
        assert result["item_status"] == "done"
        db.refresh(item)
        assert item.status == "done"
        assert item.completed_at is not None
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).first()
        assert attempt is not None
        assert attempt.assessment == "passed"
        assert attempt.evidence_summary == "时态错误+主谓不一致"

    def test_needs_retry_keeps_todo(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "needs_retry",
                    "reason": "没说出错因",
                },
                "student",
                db,
                student.id,
            )
        )
        assert result["assessment"] == "needs_retry"
        db.refresh(item)
        assert item.status == "todo"
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).first()
        assert attempt is not None
        assert attempt.assessment == "needs_retry"

    def test_blocked_marks_in_progress(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "blocked",
                    "reason": "卡住了需要帮助",
                    "evidence_summary": "学生未能独立完成第一步",
                },
                "student",
                db,
                student.id,
            )
        )
        db.refresh(item)
        assert item.status == "in_progress"

    def test_invalid_assessment_returns_error(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "invalid",
                    "reason": "x",
                },
                "student",
                db,
                student.id,
            )
        )
        assert "error" in result

    def test_unauthorized_student_returns_error(self, db):
        student = _make_student(db)
        other = _make_student(db, username="other-student")
        _, item = _make_plan_item(db, student.id)
        # other 尝试完成 student 的任务
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "passed",
                    "reason": "x",
                },
                "student",
                db,
                other.id,
            )
        )
        # role=student 时 _resolve_tool_student_id 取 JWT user_id（other.id），
        # 忽略 args.student_id；plan 属于 student.id != other.id -> 无权 -> error。
        # other 无法通过传 args.student_id 冒充（sid 只从 JWT 取）。
        assert "error" in result

    def test_passed_without_evidence_is_rejected(self, db):
        """P0 修复：passed 必须带学生作答证据，否则不标 done（防 AI 没让学生回答就判完成）。"""
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "passed",
                    "reason": "说出了错因",
                },
                "student",
                db,
                student.id,
            )
        )
        assert "error" in result
        db.refresh(item)
        assert item.status != "done"
        assert item.completed_at is None
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).first()
        assert attempt is None

    def test_passed_with_blank_evidence_is_rejected(self, db):
        """evidence_summary 只有空白也算没证据，必须 strip 后非空。"""
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        result = asyncio.run(
            _handle_complete_task_item(
                {
                    "student_id": student.id,
                    "plan_item_id": item.id,
                    "assessment": "passed",
                    "reason": "说出了错因",
                    "evidence_summary": "   \n  ",
                },
                "student",
                db,
                student.id,
            )
        )
        assert "error" in result
        db.refresh(item)
        assert item.status != "done"
