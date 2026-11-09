"""共享完成判定 service（record_study_plan_item_assessment）单测。

覆盖：
- passed 必须带非空证据（strip 后判空），否则报错且状态不变
- passed -> done + completed_at + Attempt + LearningFeedback + plan 刷新
- needs_retry -> todo、blocked -> in_progress，同样写 Attempt
- 越权 fail-closed
- 幂等：重复 passed 不重复写 Attempt/反馈
- HTTP 与 Agent 等价（同一 service）
"""

import pytest

from app.models.p2 import LearningFeedback, StudyPlan, StudyPlanItem, StudyPlanItemAttempt
from app.models.user import User
from app.features.p2.study_plan import record_study_plan_item_assessment, StudyPlanItemSchema
from app.utils.security import hash_password


def _make_student(db, username="svc-student") -> User:
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


class TestRecordStudyPlanItemAssessment:
    def test_passed_requires_non_blank_evidence(self, db):
        """passed 无证据或空白证据 -> 报错，状态不变，不写 Attempt/反馈。"""
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        for evidence in (None, "", "   \n  "):
            with pytest.raises(ValueError, match="证据"):
                record_study_plan_item_assessment(
                    db, student_id=student.id, item_id=item.id,
                    assessment="passed", evidence_summary=evidence,
                )
            db.rollback()
        db.refresh(item)
        assert item.status == "todo"
        assert item.completed_at is None
        assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).count() == 0
        assert db.query(LearningFeedback).filter_by(student_id=student.id).count() == 0

    def test_passed_writes_attempt_feedback_and_refreshes_plan(self, db):
        """合法 passed：Attempt + done + completed_at + LearningFeedback + plan completed。"""
        student = _make_student(db)
        plan, item = _make_plan_item(db, student.id)
        result = record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id,
            assessment="passed", evidence_summary="时态错误+主谓不一致", reason="说出2个错因",
        )
        assert isinstance(result, StudyPlanItemSchema)
        assert result.status == "done"
        db.refresh(item)
        assert item.status == "done"
        assert item.completed_at is not None
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).first()
        assert attempt is not None
        assert attempt.assessment == "passed"
        assert attempt.evidence_summary == "时态错误+主谓不一致"
        fb = db.query(LearningFeedback).filter_by(student_id=student.id).first()
        assert fb is not None
        assert fb.feedback_type == "duration"
        db.refresh(plan)
        assert plan.status == "completed"  # 唯一任务 done -> plan 刷新为 completed

    def test_needs_retry_keeps_todo_writes_attempt(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id,
            assessment="needs_retry", evidence_summary=None, reason="没说出错因",
        )
        db.refresh(item)
        assert item.status == "todo"
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).first()
        assert attempt is not None
        assert attempt.assessment == "needs_retry"
        # needs_retry 不产生完成反馈
        assert db.query(LearningFeedback).filter_by(student_id=student.id).count() == 0

    def test_blocked_marks_in_progress(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id,
            assessment="blocked", evidence_summary="学生未能独立完成第一步", reason="卡住了",
        )
        db.refresh(item)
        assert item.status == "in_progress"

    def test_unauthorized_student_denied(self, db):
        """越权 fail-closed：别的学生不能完成别人的计划项。"""
        student = _make_student(db)
        other = _make_student(db, username="svc-other")
        _, item = _make_plan_item(db, student.id)
        with pytest.raises(PermissionError):
            record_study_plan_item_assessment(
                db, student_id=other.id, item_id=item.id,
                assessment="passed", evidence_summary="x",
            )
        db.rollback()
        assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).count() == 0

    def test_unknown_item_raises(self, db):
        student = _make_student(db)
        with pytest.raises(Exception):
            record_study_plan_item_assessment(
                db, student_id=student.id, item_id=999999,
                assessment="passed", evidence_summary="x",
            )
        db.rollback()

    def test_repeat_passed_is_idempotent(self, db):
        """已 done 且有 passed Attempt：重复请求不重复写 Attempt/反馈。"""
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id,
            assessment="passed", evidence_summary="证据A",
        )
        completed_at = item.completed_at
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id,
            assessment="passed", evidence_summary="证据A",
        )
        assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).count() == 1
        assert db.query(LearningFeedback).filter_by(student_id=student.id).count() == 1
        db.refresh(item)
        assert item.completed_at == completed_at

    def test_invalid_assessment_rejected(self, db):
        student = _make_student(db)
        _, item = _make_plan_item(db, student.id)
        with pytest.raises(ValueError):
            record_study_plan_item_assessment(
                db, student_id=student.id, item_id=item.id,
                assessment="invalid", evidence_summary="x",
            )
        db.rollback()
