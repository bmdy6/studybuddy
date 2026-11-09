"""历史数据形态 × 新逻辑的边界测试（小萤把关发现，2026-08-06）。"""

from datetime import datetime

from app.models.p2 import StudyPlan, StudyPlanItem, StudyPlanItemAttempt
from app.features.p2.study_plan import record_study_plan_item_assessment
from app.models.user import User
from app.utils.security import hash_password


def _make_student(db, username="edge-student") -> User:
    student = User(username=username, password_hash=hash_password("x"), role="student", display_name=username)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _make_done_item_without_attempt(db, student_id: int, completed_at):
    """构造 P0 bug 期间的存量脏数据：status=done 但无 Attempt。"""
    plan = StudyPlan(student_id=student_id, title="脏数据验证")
    db.add(plan)
    db.commit()
    db.refresh(plan)
    item = StudyPlanItem(plan_id=plan.id, title="历史完成项", status="done", completed_at=completed_at)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class TestHistoricalDirtyData:
    def test_done_without_attempt_repassed_does_not_backfill_or_reset_time(self, db):
        """P1-1：历史 done 无 Attempt 再 passed -> 不补证、不重置 completed_at（防 daily record 幽灵记录）。"""
        student = _make_student(db)
        item = _make_done_item_without_attempt(db, student.id, datetime(2026, 8, 3, 9, 0))
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id, assessment="passed", evidence_summary="回顾完成"
        )
        db.refresh(item)
        assert item.completed_at == datetime(2026, 8, 3, 9, 0)
        assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id).count() == 0

    def test_needs_retry_clears_completed_at(self, db):
        """P2-1：done -> needs_retry 必须清 completed_at（与 update_study_plan_item_status 口径一致）。"""
        student = _make_student(db)
        plan = StudyPlan(student_id=student.id, title="重做验证")
        db.add(plan)
        db.commit()
        db.refresh(plan)
        item = StudyPlanItem(plan_id=plan.id, title="先完成后重做", status="todo")
        db.add(item)
        db.commit()
        db.refresh(item)
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id, assessment="passed", evidence_summary="第一次完成"
        )
        record_study_plan_item_assessment(db, student_id=student.id, item_id=item.id, assessment="needs_retry", evidence_summary=None)
        db.refresh(item)
        assert item.status == "todo"
        assert item.completed_at is None
        # needs_retry 也是新尝试，写 Attempt
        assert db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item.id, assessment="needs_retry").count() == 1

    def test_blocked_clears_completed_at(self, db):
        student = _make_student(db)
        plan = StudyPlan(student_id=student.id, title="阻塞验证")
        db.add(plan)
        db.commit()
        db.refresh(plan)
        item = StudyPlanItem(plan_id=plan.id, title="先完成后卡住", status="todo")
        db.add(item)
        db.commit()
        db.refresh(item)
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id, assessment="passed", evidence_summary="第一次完成"
        )
        record_study_plan_item_assessment(
            db, student_id=student.id, item_id=item.id, assessment="blocked",
            evidence_summary="后续复查未能说明步骤", reason="需要重新讲解",
        )
        db.refresh(item)
        assert item.status == "in_progress"
        assert item.completed_at is None
