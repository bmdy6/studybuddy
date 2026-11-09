"""家庭目标与任务激励 service 单测（批次 1）。

覆盖状态机、幂等、金额快照与权限边界：
- 建任务时金额两级都空 -> 拒绝
- once 任务建房即生成当天 occurrence；daily 惰性生成且重复调用不新增
- 提交需图片或非空文字；空白文字不算证据
- 只能提交自己的 occurrence；pending/rejected 才能提交；已提交不能重复提交
- 打勾幂等（第二次 409 且不产生第二条奖励记录）
- 金额确认后快照，后续改任务金额不影响历史记录
- 驳回必须填理由且不改状态
- 非绑定家长无权访问学生
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.features.family_goal import service
from app.models.family_goal import (
    FamilyGoal,
    FamilyGoalTask,
    FamilyRewardRecord,
    FamilyTaskEvidence,
    FamilyTaskOccurrence,
)
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.utils.security import hash_password


def _make_user(db, role: str, username: str) -> User:
    user = User(username=username, password_hash=hash_password("x"), role=role, display_name=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _bind(db, parent: User, student: User) -> None:
    db.add(TeacherStudent(teacher_id=parent.id, student_id=student.id))
    db.commit()


def _make_goal(db, student: User, *, reward: str | None = "5.00") -> FamilyGoal:
    return service.create_goal(
        db,
        student_id=student.id,
        created_by=student.id,
        creator_role="student",
        title="英语默写",
        reward_amount=Decimal(reward) if reward is not None else None,
    )


def _make_task(db, student: User, goal: FamilyGoal, *, reward: str | None = None, repeat_type: str = "once"):
    return service.create_task(
        db,
        goal_id=goal.id,
        student_id=student.id,
        created_by=student.id,
        title="默写英语单词",
        repeat_type=repeat_type,
        reward_amount=Decimal(reward) if reward is not None else None,
    )


class TestTaskRewardAmount:
    def test_task_without_reward_and_goal_without_reward_is_rejected(self, db):
        student = _make_user(db, "student", "fg-no-amount-student")
        goal = _make_goal(db, student, reward=None)
        with pytest.raises(service.FamilyGoalError) as exc:
            _make_task(db, student, goal)
        assert exc.value.status_code == 422
        assert db.query(FamilyGoalTask).filter_by(goal_id=goal.id).count() == 0

    def test_task_inherits_goal_reward_amount(self, db):
        student = _make_user(db, "student", "fg-inherit-student")
        goal = _make_goal(db, student, reward="5.00")
        task = _make_task(db, student, goal)
        assert service.resolve_reward_amount(task, goal) == Decimal("5.00")

    def test_task_reward_overrides_goal_reward(self, db):
        student = _make_user(db, "student", "fg-override-student")
        goal = _make_goal(db, student, reward="5.00")
        task = _make_task(db, student, goal, reward="8.00")
        assert service.resolve_reward_amount(task, goal) == Decimal("8.00")


class TestOccurrenceGeneration:
    def test_once_task_creates_today_occurrence_immediately(self, db):
        student = _make_user(db, "student", "fg-once-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrences = db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).all()
        assert len(occurrences) == 1
        assert occurrences[0].occurrence_date == service.today_in_app_timezone()
        assert occurrences[0].status == "pending"

    def test_daily_task_generates_occurrence_lazily_and_only_once(self, db):
        student = _make_user(db, "student", "fg-daily-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal, repeat_type="daily")
        assert db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).count() == 0

        today = service.today_in_app_timezone()
        assert service.ensure_occurrences(db, student_id=student.id, on_date=today) == 1
        assert service.ensure_occurrences(db, student_id=student.id, on_date=today) == 0
        assert db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).count() == 1

        tomorrow = today + timedelta(days=1)
        assert service.ensure_occurrences(db, student_id=student.id, on_date=tomorrow) == 1
        assert db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).count() == 2

    def test_today_tasks_expose_resolved_amount_and_goal_title(self, db):
        student = _make_user(db, "student", "fg-today-student")
        goal = _make_goal(db, student, reward="5.00")
        _make_task(db, student, goal)
        items = service.list_today_tasks(db, student_id=student.id, on_date=service.today_in_app_timezone())
        assert len(items) == 1
        assert items[0]["title"] == "默写英语单词"
        assert items[0]["goal_title"] == "英语默写"
        assert items[0]["reward_amount"] == "5.00"
        assert items[0]["status"] == "pending"


def _occurrence_of(db, task) -> FamilyTaskOccurrence:
    """按本次创建的任务取实例：绝不能用全局 .first()，开发库里还有别的账号数据。"""
    return db.query(FamilyTaskOccurrence).filter(FamilyTaskOccurrence.task_id == task.id).one()


class TestSubmitOccurrence:
    def test_submit_requires_image_or_note(self, db):
        student = _make_user(db, "student", "fg-empty-submit-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        with pytest.raises(service.FamilyGoalError):
            service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="   ", evidence_refs=[])
        db.refresh(occurrence)
        assert occurrence.status == "pending"

    def test_submit_with_note_only_succeeds(self, db):
        student = _make_user(db, "student", "fg-note-submit-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note=" 默写完 3 单元 ", evidence_refs=[])
        db.refresh(occurrence)
        assert occurrence.status == "submitted"
        assert occurrence.submit_note == "默写完 3 单元"
        assert occurrence.submitted_at is not None

    def test_submit_with_images_persists_evidence_rows(self, db):
        student = _make_user(db, "student", "fg-image-submit-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        service.submit_occurrence(
            db,
            occurrence_id=occurrence.id,
            student_id=student.id,
            note="",
            evidence_refs=["local:family_goal/2026/09/a.jpg", "local:family_goal/2026/09/b.jpg"],
        )
        rows = db.query(FamilyTaskEvidence).filter_by(occurrence_id=occurrence.id).order_by(FamilyTaskEvidence.sort_order).all()
        assert [row.content_ref for row in rows] == [
            "local:family_goal/2026/09/a.jpg",
            "local:family_goal/2026/09/b.jpg",
        ]

    def test_cannot_submit_twice(self, db):
        student = _make_user(db, "student", "fg-twice-submit-student")
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="第一次", evidence_refs=[])
        with pytest.raises(service.FamilyGoalError) as exc:
            service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="第二次", evidence_refs=[])
        assert exc.value.status_code == 409
        db.refresh(occurrence)
        assert occurrence.submit_note == "第一次"

    def test_resubmit_after_reject_replaces_note_and_evidence(self, db):
        student = _make_user(db, "student", "fg-resubmit-student")
        parent = _make_user(db, "teacher", "fg-resubmit-parent")
        _bind(db, parent, student)
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="旧提交", evidence_refs=["local:a.jpg"])
        service.review_occurrence(db, occurrence_id=occurrence.id, approve=False, reason="拍糊了", reviewer_id=parent.id)

        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="重拍", evidence_refs=["local:b.jpg"])
        db.refresh(occurrence)
        assert occurrence.status == "submitted"
        assert occurrence.submit_note == "重拍"
        rows = db.query(FamilyTaskEvidence).filter_by(occurrence_id=occurrence.id).all()
        assert [row.content_ref for row in rows] == ["local:b.jpg"]

    def test_student_cannot_submit_other_student_occurrence(self, db):
        owner = _make_user(db, "student", "fg-owner-student")
        intruder = _make_user(db, "student", "fg-intruder-student")
        goal = _make_goal(db, owner)
        task = _make_task(db, owner, goal)
        occurrence = _occurrence_of(db, task)
        with pytest.raises(service.FamilyGoalError) as exc:
            service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=intruder.id, note="我来交", evidence_refs=[])
        assert exc.value.status_code == 403


class TestReviewOccurrence:
    def _submitted_occurrence(self, db, student, *, note="默写完 3 单元"):
        goal = _make_goal(db, student)
        _make_task(db, student, goal)
        occurrence = db.query(FamilyTaskOccurrence).filter_by(student_id=student.id).first()
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note=note, evidence_refs=[])
        return occurrence

    def test_approve_creates_reward_record_with_snapshot(self, db):
        student = _make_user(db, "student", "fg-approve-student")
        parent = _make_user(db, "teacher", "fg-approve-parent")
        _bind(db, parent, student)
        occurrence = self._submitted_occurrence(db, student)

        service.review_occurrence(db, occurrence_id=occurrence.id, approve=True, reviewer_id=parent.id)

        db.refresh(occurrence)
        assert occurrence.status == "approved"
        assert occurrence.reviewed_by == parent.id
        assert occurrence.reward_amount_snapshot == Decimal("5.00")
        reward = db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence.id).one()
        assert reward.amount == Decimal("5.00")
        assert reward.task_title == "默写英语单词"
        assert reward.goal_title == "英语默写"
        assert reward.confirmed_by == parent.id

    def test_approve_is_idempotent(self, db):
        student = _make_user(db, "student", "fg-idem-student")
        parent = _make_user(db, "teacher", "fg-idem-parent")
        _bind(db, parent, student)
        occurrence = self._submitted_occurrence(db, student)

        service.review_occurrence(db, occurrence_id=occurrence.id, approve=True, reviewer_id=parent.id)
        with pytest.raises(service.FamilyGoalError) as exc:
            service.review_occurrence(db, occurrence_id=occurrence.id, approve=True, reviewer_id=parent.id)
        assert exc.value.status_code == 409
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence.id).count() == 1

    def test_confirmed_reward_survives_task_amount_change(self, db):
        student = _make_user(db, "student", "fg-snapshot-student")
        parent = _make_user(db, "teacher", "fg-snapshot-parent")
        _bind(db, parent, student)
        occurrence = self._submitted_occurrence(db, student)

        service.review_occurrence(db, occurrence_id=occurrence.id, approve=True, reviewer_id=parent.id)
        task = db.get(FamilyGoalTask, occurrence.task_id)
        task.reward_amount = Decimal("9.00")
        db.commit()

        db.refresh(occurrence)
        reward = db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence.id).one()
        assert reward.amount == Decimal("5.00")
        assert occurrence.reward_amount_snapshot == Decimal("5.00")

    def test_reject_requires_reason_and_keeps_state(self, db):
        student = _make_user(db, "student", "fg-reject-student")
        parent = _make_user(db, "teacher", "fg-reject-parent")
        _bind(db, parent, student)
        occurrence = self._submitted_occurrence(db, student)

        with pytest.raises(service.FamilyGoalError):
            service.review_occurrence(db, occurrence_id=occurrence.id, approve=False, reason="  ", reviewer_id=parent.id)
        db.refresh(occurrence)
        assert occurrence.status == "submitted"

        service.review_occurrence(db, occurrence_id=occurrence.id, approve=False, reason="拍糊了，重拍", reviewer_id=parent.id)
        db.refresh(occurrence)
        assert occurrence.status == "rejected"
        assert occurrence.reject_reason == "拍糊了，重拍"
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence.id).count() == 0

    def test_review_pending_occurrence_is_rejected(self, db):
        student = _make_user(db, "student", "fg-pending-review-student")
        parent = _make_user(db, "teacher", "fg-pending-review-parent")
        _bind(db, parent, student)
        goal = _make_goal(db, student)
        task = _make_task(db, student, goal)
        occurrence = _occurrence_of(db, task)
        with pytest.raises(service.FamilyGoalError) as exc:
            service.review_occurrence(db, occurrence_id=occurrence.id, approve=True, reviewer_id=parent.id)
        assert exc.value.status_code == 409


class TestAccessAndSummary:
    def test_unbound_parent_cannot_access_student(self, db):
        student = _make_user(db, "student", "fg-access-student")
        stranger = _make_user(db, "teacher", "fg-access-stranger")
        with pytest.raises(service.FamilyGoalError) as exc:
            service.assert_can_access_student(db, user=stranger, student_id=student.id)
        assert exc.value.status_code == 403

    def test_student_cannot_access_other_student(self, db):
        student = _make_user(db, "student", "fg-access-owner")
        other = _make_user(db, "student", "fg-access-other")
        with pytest.raises(service.FamilyGoalError) as exc:
            service.assert_can_access_student(db, user=other, student_id=student.id)
        assert exc.value.status_code == 403

    def test_bound_parent_can_access_student(self, db):
        student = _make_user(db, "student", "fg-access-bound-student")
        parent = _make_user(db, "teacher", "fg-access-bound-parent")
        _bind(db, parent, student)
        service.assert_can_access_student(db, user=parent, student_id=student.id)

    def test_reward_summary_totals_approved_records(self, db):
        student = _make_user(db, "student", "fg-summary-student")
        parent = _make_user(db, "teacher", "fg-summary-parent")
        _bind(db, parent, student)
        goal = _make_goal(db, student, reward="5.00")
        task = _make_task(db, student, goal, repeat_type="daily")

        today = service.today_in_app_timezone()
        service.ensure_occurrences(db, student_id=student.id, on_date=today)
        service.ensure_occurrences(db, student_id=student.id, on_date=today - timedelta(days=1))
        occurrences = (
            db.query(FamilyTaskOccurrence)
            .filter(FamilyTaskOccurrence.task_id == task.id)
            .order_by(FamilyTaskOccurrence.id)
            .all()
        )
        assert len(occurrences) == 2
        service.submit_occurrence(db, occurrence_id=occurrences[0].id, student_id=student.id, note="昨天补交", evidence_refs=[])
        service.review_occurrence(db, occurrence_id=occurrences[0].id, approve=True, reviewer_id=parent.id)

        summary = service.reward_summary(db, student_id=student.id)
        assert summary["total_amount"] == "5.00"
        assert len(summary["records"]) == 1
        assert summary["records"][0]["task_title"] == "默写英语单词"

    def test_list_pending_occurrences_only_returns_submitted(self, db):
        student = _make_user(db, "student", "fg-pending-list-student")
        goal = _make_goal(db, student, reward="5.00")
        task = _make_task(db, student, goal, repeat_type="daily")
        today = service.today_in_app_timezone()
        service.ensure_occurrences(db, student_id=student.id, on_date=today)

        assert service.list_pending_occurrences(db, student_id=student.id) == []
        occurrence = _occurrence_of(db, task)
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=student.id, note="交了", evidence_refs=[])
        pending = service.list_pending_occurrences(db, student_id=student.id)
        assert len(pending) == 1
        assert pending[0]["occurrence_id"] == occurrence.id
        assert pending[0]["reward_amount"] == "5.00"
        assert pending[0]["occurrence_date"] == today.isoformat()


def test_today_in_app_timezone_returns_date():
    assert isinstance(service.today_in_app_timezone(), date)
