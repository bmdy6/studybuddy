"""家庭目标与任务激励 API 集成测试（批次 2）。

覆盖：目标/任务 CRUD 与金额校验、今日任务、图片上传白名单、提交门禁、越权边界，
以及内部集成入口（X-Internal-Token）的待审列表 / 打勾 / 驳回 / 奖励汇总。

COS 真实上传不在测试范围，upload_file 用 patch mock。
"""

import io
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import reveal_secret, settings
from app.models.family_goal import FamilyRewardRecord, FamilyTaskOccurrence
from app.models.user import User
from app.utils.security import hash_password

STUDENT_ID = 2
TEACHER_ID = 1  # conftest 已把 teacher(1) 绑定到 student(2)


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal_h() -> dict:
    return {"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)}


def _make_user(db: Session, role: str, prefix: str) -> User:
    user = User(
        username=f"{prefix}_{uuid4().hex[:10]}",
        password_hash=hash_password("x"),
        role=role,
        display_name=prefix,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_goal(client: TestClient, headers: dict, student_id: int = STUDENT_ID, **overrides) -> dict:
    payload = {"title": "英语默写", "reward_amount": "5.00"}
    payload.update(overrides)
    r = client.post(f"/api/students/{student_id}/family-goals", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _create_task(client: TestClient, headers: dict, goal_id: int, **overrides) -> dict:
    payload = {"title": "默写英语单词", "repeat_type": "once"}
    payload.update(overrides)
    r = client.post(f"/api/family-goals/{goal_id}/tasks", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestGoalAndTaskApi:
    def test_student_goal_and_task_appear_in_today_tasks(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token))
        task = _create_task(client, _h(token), goal["id"])

        r = client.get(f"/api/students/{STUDENT_ID}/today-family-tasks", headers=_h(token))
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert items[0]["occurrence_id"] > 0
        assert items[0]["task_id"] == task["id"]
        assert items[0]["title"] == "默写英语单词"
        assert items[0]["goal_title"] == "英语默写"
        assert items[0]["reward_amount"] == "5.00"
        assert items[0]["status"] == "pending"
        assert items[0]["student_id"] == STUDENT_ID

    def test_student_cannot_create_goal_for_other_student(self, client: TestClient, db: Session):
        other = _make_user(db, "student", "fg-api-other")
        token = _student_token(client)
        r = client.post(
            f"/api/students/{other.id}/family-goals",
            json={"title": "偷建目标", "reward_amount": "5.00"},
            headers=_h(token),
        )
        assert r.status_code == 403

    def test_parent_creates_goal_for_bound_child(self, client: TestClient, db: Session):
        token = _teacher_token(client)
        goal = _create_goal(client, _h(token))
        assert goal["creator_role"] == "parent"
        assert goal["student_id"] == STUDENT_ID

    def test_parent_cannot_create_goal_for_unbound_student(self, client: TestClient, db: Session):
        stranger = _make_user(db, "student", "fg-api-stranger")
        token = _teacher_token(client)
        r = client.post(
            f"/api/students/{stranger.id}/family-goals",
            json={"title": "别人家孩子", "reward_amount": "5.00"},
            headers=_h(token),
        )
        assert r.status_code == 403

    def test_task_without_any_reward_amount_is_rejected(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token), reward_amount=None)
        r = client.post(
            f"/api/family-goals/{goal['id']}/tasks",
            json={"title": "没有金额的任务"},
            headers=_h(token),
        )
        assert r.status_code == 422
        assert "奖励金额" in r.json()["detail"]

    def test_blank_goal_title_is_rejected(self, client: TestClient, db: Session):
        token = _student_token(client)
        r = client.post(
            f"/api/students/{STUDENT_ID}/family-goals",
            json={"title": "   ", "reward_amount": "5.00"},
            headers=_h(token),
        )
        assert r.status_code == 422

    def test_daily_task_generates_single_occurrence_per_day(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token))
        _create_task(client, _h(token), goal["id"], repeat_type="daily")

        for _ in range(3):
            r = client.get(f"/api/students/{STUDENT_ID}/today-family-tasks", headers=_h(token))
            assert r.status_code == 200
            assert len(r.json()) == 1
        assert db.query(FamilyTaskOccurrence).filter_by(student_id=STUDENT_ID).count() == 1


class TestEvidenceAndSubmitApi:
    def _pending_occurrence_id(self, client: TestClient, headers: dict) -> int:
        r = client.get(f"/api/students/{STUDENT_ID}/today-family-tasks", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()[0]["occurrence_id"]

    def test_upload_rejects_non_image(self, client: TestClient, db: Session):
        token = _student_token(client)
        r = client.post(
            "/api/family-task-evidence/upload",
            headers=_h(token),
            files={"file": ("homework.pdf", io.BytesIO(b"pdf"), "application/pdf")},
        )
        assert r.status_code == 415

    def test_upload_image_then_submit_keeps_evidence(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token))
        _create_task(client, _h(token), goal["id"])
        occurrence_id = self._pending_occurrence_id(client, _h(token))

        fake_key = f"family_goal/2026/09/{uuid4().hex}.jpg"
        with patch("app.features.family_goal.router.upload_file", return_value=fake_key):
            r = client.post(
                "/api/family-task-evidence/upload",
                headers=_h(token),
                files={"file": ("evidence.jpg", io.BytesIO(b"fakejpg"), "image/jpeg")},
            )
        assert r.status_code == 201, r.text
        assert r.json()["content_ref"] == fake_key
        assert r.json()["url"].endswith(fake_key)

        r = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "默写完 3 单元", "evidence_refs": [fake_key]},
            headers=_h(token),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "submitted"
        assert data["submit_note"] == "默写完 3 单元"
        assert len(data["evidence"]) == 1
        assert data["evidence"][0]["url"].endswith(fake_key)
        assert data["submitted_at"]

    def test_submit_without_evidence_is_rejected(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token))
        _create_task(client, _h(token), goal["id"])
        occurrence_id = self._pending_occurrence_id(client, _h(token))

        r = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "   ", "evidence_refs": []},
            headers=_h(token),
        )
        assert r.status_code == 422
        assert db.get(FamilyTaskOccurrence, occurrence_id).status == "pending"

    def test_submit_twice_is_conflict(self, client: TestClient, db: Session):
        token = _student_token(client)
        goal = _create_goal(client, _h(token))
        _create_task(client, _h(token), goal["id"])
        occurrence_id = self._pending_occurrence_id(client, _h(token))

        first = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "第一次", "evidence_refs": []},
            headers=_h(token),
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "第二次", "evidence_refs": []},
            headers=_h(token),
        )
        assert second.status_code == 409

    def test_student_cannot_submit_other_student_occurrence(self, client: TestClient, db: Session):
        from app.features.family_goal import service

        other = _make_user(db, "student", "fg-api-victim")
        goal = service.create_goal(
            db,
            student_id=other.id,
            created_by=other.id,
            creator_role="student",
            title="别人的目标",
            reward_amount=None,
        )
        task = service.create_task(
            db,
            goal_id=goal.id,
            student_id=other.id,
            created_by=other.id,
            title="别人的任务",
            reward_amount=service.parse_amount("5"),
        )
        occurrence = db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).one()

        token = _student_token(client)
        r = client.post(
            f"/api/family-task-occurrences/{occurrence.id}/submit",
            json={"note": "我来交作业", "evidence_refs": []},
            headers=_h(token),
        )
        assert r.status_code == 403

    def test_parent_cannot_submit_occurrence(self, client: TestClient, db: Session):
        student_token = _student_token(client)
        goal = _create_goal(client, _h(student_token))
        _create_task(client, _h(student_token), goal["id"])
        occurrence_id = self._pending_occurrence_id(client, _h(student_token))

        parent_token = _teacher_token(client)
        r = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "家长代交", "evidence_refs": []},
            headers=_h(parent_token),
        )
        assert r.status_code == 403


class TestIntegrationApi:
    def _submitted_occurrence(self, client: TestClient) -> int:
        student_token = _student_token(client)
        goal = _create_goal(client, _h(student_token))
        _create_task(client, _h(student_token), goal["id"])
        r = client.get(f"/api/students/{STUDENT_ID}/today-family-tasks", headers=_h(student_token))
        occurrence_id = r.json()[0]["occurrence_id"]
        submitted = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "默写完 3 单元", "evidence_refs": []},
            headers=_h(student_token),
        )
        assert submitted.status_code == 200, submitted.text
        return occurrence_id

    def test_requires_internal_token(self, client: TestClient, db: Session):
        occurrence_id = self._submitted_occurrence(client)
        assert client.get(f"/api/integration/family-tasks/pending?student_id={STUDENT_ID}").status_code == 403
        assert client.post(f"/api/integration/family-tasks/{occurrence_id}/approve").status_code == 403
        assert (
            client.get(
                f"/api/integration/family-tasks/pending?student_id={STUDENT_ID}",
                headers={"X-Internal-Token": "wrong"},
            ).status_code
            == 403
        )

    def test_pending_list_and_approve_flow_is_idempotent(self, client: TestClient, db: Session):
        occurrence_id = self._submitted_occurrence(client)

        r = client.get(
            f"/api/integration/family-tasks/pending?student_id={STUDENT_ID}", headers=_internal_h()
        )
        assert r.status_code == 200, r.text
        pending = r.json()
        assert len(pending) == 1
        assert pending[0]["occurrence_id"] == occurrence_id
        assert pending[0]["reward_amount"] == "5.00"
        assert pending[0]["submit_note"] == "默写完 3 单元"

        approved = client.post(
            f"/api/integration/family-tasks/{occurrence_id}/approve", headers=_internal_h()
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        again = client.post(f"/api/integration/family-tasks/{occurrence_id}/approve", headers=_internal_h())
        assert again.status_code == 409
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence_id).count() == 1

        record = db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence_id).one()
        assert str(record.amount) == "5.00"
        assert record.confirmed_by == TEACHER_ID  # 绑定的唯一家长
        assert record.task_title == "默写英语单词"

        left = client.get(f"/api/integration/family-tasks/pending?student_id={STUDENT_ID}", headers=_internal_h())
        assert left.json() == []

        rewards = client.get(
            f"/api/integration/family-tasks/students/{STUDENT_ID}/rewards", headers=_internal_h()
        )
        assert rewards.status_code == 200, rewards.text
        assert rewards.json()["total_amount"] == "5.00"

    def test_reject_requires_reason_then_allows_resubmit(self, client: TestClient, db: Session):
        occurrence_id = self._submitted_occurrence(client)

        no_reason = client.post(
            f"/api/integration/family-tasks/{occurrence_id}/reject",
            json={"reason": "  "},
            headers=_internal_h(),
        )
        assert no_reason.status_code == 422

        rejected = client.post(
            f"/api/integration/family-tasks/{occurrence_id}/reject",
            json={"reason": "拍糊了，重拍"},
            headers=_internal_h(),
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["reject_reason"] == "拍糊了，重拍"

        student_token = _student_token(client)
        resubmit = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "重拍好了", "evidence_refs": ["local:family_goal/2026/09/retake.jpg"]},
            headers=_h(student_token),
        )
        assert resubmit.status_code == 200, resubmit.text
        assert resubmit.json()["status"] == "submitted"
        assert resubmit.json()["reject_reason"] is None

    def test_parent_reward_summary_matches_confirmed_records(self, client: TestClient, db: Session):
        occurrence_id = self._submitted_occurrence(client)
        client.post(f"/api/integration/family-tasks/{occurrence_id}/approve", headers=_internal_h())

        parent_token = _teacher_token(client)
        r = client.get(f"/api/students/{STUDENT_ID}/family-rewards", headers=_h(parent_token))
        assert r.status_code == 200, r.text
        summary = r.json()
        assert summary["total_amount"] == "5.00"
        assert len(summary["records"]) == 1
        assert summary["records"][0]["amount"] == "5.00"

    def test_student_cannot_read_other_student_rewards(self, client: TestClient, db: Session):
        stranger = _make_user(db, "student", "fg-api-rewards-stranger")
        token = _student_token(client)
        r = client.get(f"/api/students/{stranger.id}/family-rewards", headers=_h(token))
        assert r.status_code == 403


class TestParentReviewApi:
    """家长走 JWT 审核（个人工作台卡片用），不依赖内部 token。"""

    def _submitted(self, client: TestClient) -> int:
        student_token = _student_token(client)
        goal = _create_goal(client, _h(student_token))
        _create_task(client, _h(student_token), goal["id"])
        r = client.get(f"/api/students/{STUDENT_ID}/today-family-tasks", headers=_h(student_token))
        occurrence_id = r.json()[0]["occurrence_id"]
        submitted = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/submit",
            json={"note": "默写完 3 单元", "evidence_refs": ["local:family_goal/2026/09/x.jpg"]},
            headers=_h(student_token),
        )
        assert submitted.status_code == 200, submitted.text
        return occurrence_id

    def test_parent_lists_pending_reviews(self, client: TestClient, db: Session):
        occurrence_id = self._submitted(client)
        token = _teacher_token(client)
        r = client.get(f"/api/students/{STUDENT_ID}/family-task-reviews", headers=_h(token))
        assert r.status_code == 200, r.text
        items = r.json()
        assert [item["occurrence_id"] for item in items] == [occurrence_id]
        assert items[0]["submit_note"] == "默写完 3 单元"
        assert items[0]["evidence"][0]["url"].endswith(".jpg")

    def test_parent_approves_and_reward_uses_login_user(self, client: TestClient, db: Session):
        occurrence_id = self._submitted(client)
        token = _teacher_token(client)
        r = client.post(f"/api/family-task-occurrences/{occurrence_id}/approve", headers=_h(token))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        record = db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence_id).one()
        assert record.confirmed_by == TEACHER_ID

        # 重复确认冲突，且不再产生第二条奖励
        again = client.post(f"/api/family-task-occurrences/{occurrence_id}/approve", headers=_h(token))
        assert again.status_code == 409
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence_id).count() == 1

        # 确认后不在待审列表
        left = client.get(f"/api/students/{STUDENT_ID}/family-task-reviews", headers=_h(token))
        assert left.json() == []

    def test_parent_rejects_with_reason(self, client: TestClient, db: Session):
        occurrence_id = self._submitted(client)
        token = _teacher_token(client)

        no_reason = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/reject", json={"reason": ""}, headers=_h(token)
        )
        assert no_reason.status_code == 422

        rejected = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/reject",
            json={"reason": "拍糊了"},
            headers=_h(token),
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

    def test_student_cannot_approve_own_submission(self, client: TestClient, db: Session):
        """学生不能给自己发奖励：自己审自己的提交必须 403（回归 2026-09-30 演练发现的越权）。"""
        occurrence_id = self._submitted(client)
        student_token = _student_token(client)
        r = client.post(
            f"/api/family-task-occurrences/{occurrence_id}/approve", headers=_h(student_token)
        )
        assert r.status_code == 403
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence_id).count() == 0

    def test_unbound_parent_cannot_review(self, client: TestClient, db: Session):
        """家长只能审自己绑定孩子的提交：审别人家孩子的提交必须 403。"""
        from app.features.family_goal import service

        other_student = _make_user(db, "student", "fg-api-unbound-child")
        goal = service.create_goal(
            db,
            student_id=other_student.id,
            created_by=other_student.id,
            creator_role="student",
            title="别人家目标",
            reward_amount=None,
        )
        task = service.create_task(
            db,
            goal_id=goal.id,
            student_id=other_student.id,
            created_by=other_student.id,
            title="别人家任务",
            reward_amount=service.parse_amount("3"),
        )
        occurrence = db.query(FamilyTaskOccurrence).filter_by(task_id=task.id).one()
        service.submit_occurrence(
            db, occurrence_id=occurrence.id, student_id=other_student.id, note="交了", evidence_refs=[]
        )

        token = _teacher_token(client)
        r = client.post(f"/api/family-task-occurrences/{occurrence.id}/approve", headers=_h(token))
        assert r.status_code == 403
        assert db.query(FamilyRewardRecord).filter_by(occurrence_id=occurrence.id).count() == 0

    def test_student_cannot_review_other_student_occurrence(self, client: TestClient, db: Session):
        from app.features.family_goal import service

        other = _make_user(db, "student", "fg-api-review-victim")
        goal = service.create_goal(
            db,
            student_id=other.id,
            created_by=other.id,
            creator_role="student",
            title="别人的目标",
            reward_amount=None,
        )
        task = service.create_task(
            db,
            goal_id=goal.id,
            student_id=other.id,
            created_by=other.id,
            title="别人的任务",
            reward_amount=service.parse_amount("5"),
        )
        occurrence = (
            db.query(FamilyTaskOccurrence)
            .filter_by(task_id=task.id)
            .one()
        )
        service.submit_occurrence(db, occurrence_id=occurrence.id, student_id=other.id, note="交了", evidence_refs=[])

        token = _student_token(client)
        r = client.post(f"/api/family-task-occurrences/{occurrence.id}/approve", headers=_h(token))
        assert r.status_code == 403


class TestFamilyGoalContextApi:
    """没绑家长时前端要知道，否则孩子交了作业永远停在「待家长确认」。"""

    def test_bound_parent_returns_true(self, client: TestClient):
        """conftest 已把 teacher(1) 绑到 student(2)，学生自查应为已绑定。"""
        token = _student_token(client)
        r = client.get(f"/api/students/{STUDENT_ID}/family-goal-context", headers=_h(token))
        assert r.status_code == 200, r.text
        assert r.json() == {"parent_bound": True}

    def test_unbound_student_returns_false(self, client: TestClient, db: Session):
        from app.models.teacher_student import TeacherStudent

        db.query(TeacherStudent).filter(
            TeacherStudent.teacher_id == TEACHER_ID, TeacherStudent.student_id == STUDENT_ID
        ).delete(synchronize_session=False)
        db.commit()

        token = _student_token(client)
        r = client.get(f"/api/students/{STUDENT_ID}/family-goal-context", headers=_h(token))
        assert r.status_code == 200, r.text
        assert r.json() == {"parent_bound": False}

    def test_student_cannot_query_other_student(self, client: TestClient, db: Session):
        other = _make_user(db, "student", "fg-ctx-other")
        token = _student_token(client)
        r = client.get(f"/api/students/{other.id}/family-goal-context", headers=_h(token))
        assert r.status_code == 403

    def test_parent_cannot_query_unbound_student(self, client: TestClient, db: Session):
        stranger = _make_user(db, "student", "fg-ctx-stranger")
        token = _teacher_token(client)
        r = client.get(f"/api/students/{stranger.id}/family-goal-context", headers=_h(token))
        assert r.status_code == 403

    def test_parent_can_query_bound_student(self, client: TestClient):
        token = _teacher_token(client)
        r = client.get(f"/api/students/{STUDENT_ID}/family-goal-context", headers=_h(token))
        assert r.status_code == 200, r.text
        assert r.json() == {"parent_bound": True}
