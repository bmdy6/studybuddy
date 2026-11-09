"""P2.1 router 集成测试（兴趣/反馈/推荐/属性面板端到端 + 权限）。

覆盖：
- parent 添加兴趣 → 200；student 自己添加兴趣 → 200
- student 提交反馈 → 200；parent 提交 → 403
- parent 初始化属性面板 → 200；student 初始化 → 403
- 查询属性（未初始化返回 None）
- 查询属性历史
- 推荐列表 + 标记点击
- 学习计划创建/查询/计划项完成
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.p2 import StudentAttribute
from app.models.user import User
from app.features.p2 import recommendation


def _teacher_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "teacher", "password": "teacher123"}).json()["access_token"]


def _student_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]


class TestInterestAPI:
    """兴趣接口 + 权限。"""

    def test_parent_add_interest(self, client):
        token = _teacher_token(client)
        r = client.post("/api/students/2/interests", json={"tag": "家长建议兴趣-围棋"}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["tag"] == "家长建议兴趣-围棋"
        assert r.json()["approved"] is False

    def test_blank_interest_is_rejected(self, client):
        token = _student_token(client)
        before = client.get("/api/students/2/interests", headers={"Authorization": f"Bearer {token}"}).json()
        r = client.post("/api/students/2/interests", json={"tag": "   "}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422
        after = client.get("/api/students/2/interests", headers={"Authorization": f"Bearer {token}"}).json()
        assert len(after) == len(before)

    def test_student_can_add_own_interest(self, client):
        token = _student_token(client)
        r = client.post("/api/students/2/interests", json={"tag": "学生自选兴趣-科幻"}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["tag"] == "学生自选兴趣-科幻"
        assert r.json()["approved"] is True

    def test_list_interests(self, client):
        token = _teacher_token(client)
        client.post("/api/students/2/interests", json={"tag": "列表兴趣-天文"}, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/students/2/interests", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_student_can_confirm_inferred_interest(self, client):
        teacher_token = _teacher_token(client)
        created = client.post("/api/students/2/interests", json={"tag": "待确认兴趣-天文"}, headers={"Authorization": f"Bearer {teacher_token}"})
        assert created.status_code == 200
        assert created.json()["approved"] is False

        student_token = _student_token(client)
        confirmed = client.patch(
            f"/api/interests/{created.json()['id']}",
            json={"approved": True},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["approved"] is True

    def test_parent_cannot_confirm_interest_for_student(self, client):
        teacher_token = _teacher_token(client)
        created = client.post("/api/students/2/interests", json={"tag": "待确认兴趣-音乐"}, headers={"Authorization": f"Bearer {teacher_token}"})

        confirmed = client.patch(
            f"/api/interests/{created.json()['id']}",
            json={"approved": True},
            headers={"Authorization": f"Bearer {teacher_token}"},
        )
        assert confirmed.status_code == 403

    def test_student_can_remove_interest(self, client):
        teacher_token = _teacher_token(client)
        created = client.post("/api/students/2/interests", json={"tag": "待移除兴趣-游戏"}, headers={"Authorization": f"Bearer {teacher_token}"})

        student_token = _student_token(client)
        removed = client.delete(f"/api/interests/{created.json()['id']}", headers={"Authorization": f"Bearer {student_token}"})
        assert removed.status_code == 204

        listed = client.get("/api/students/2/interests", headers={"Authorization": f"Bearer {student_token}"})
        assert all(item["id"] != created.json()["id"] for item in listed.json())


class TestFeedbackAPI:
    """反馈接口 + 权限。"""

    def test_student_submit_feedback(self, client):
        token = _student_token(client)
        r = client.post(
            "/api/students/2/feedback", json={"feedback_type": "duration", "content": "背了20个单词"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200

    def test_blank_feedback_is_rejected(self, client):
        token = _student_token(client)
        before = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"}).json()
        r = client.post(
            "/api/students/2/feedback", json={"feedback_type": "duration", "content": "   "}, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 422
        after = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"}).json()
        assert len(after) == len(before)

    def test_parent_cannot_submit_feedback(self, client):
        token = _teacher_token(client)
        r = client.post(
            "/api/students/2/feedback", json={"feedback_type": "duration", "content": "test"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403

    def test_list_feedback(self, client):
        token = _student_token(client)
        client.post(
            "/api/students/2/feedback", json={"feedback_type": "self_assess", "content": "感觉会了"}, headers={"Authorization": f"Bearer {token}"}
        )
        r = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


class TestStudyPlanAPI:
    """学习计划接口 + 状态流转。"""

    def test_create_and_list_study_plan(self, client):
        token = _teacher_token(client)
        payload = {
            "title": "今晚英语时态补漏",
            "focus": "一般过去时和 there be",
            "planned_date": date.today().isoformat(),
            "items": [
                {"title": "复盘错题", "target": "说出 2 个错因", "minutes": 15, "related_tags": ["一般过去时"]},
                {"title": "做 5 道专项题", "target": "错题当场订正", "minutes": 20, "related_tags": ["there be句型"]},
            ],
        }

        created = client.post("/api/students/2/study-plans", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert created.status_code == 200, created.text
        data = created.json()
        assert data["title"] == payload["title"]
        assert len(data["items"]) == 2
        assert data["reminder_message"] == "今天计划「今晚英语时态补漏」还有 2 个任务，建议先做「复盘错题」。"

        listed = client.get("/api/students/2/study-plans", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        assert any(plan["id"] == data["id"] for plan in listed.json())

    def test_update_study_plan_via_api(self, client):
        token = _teacher_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={"title": "原计划", "items": [{"title": "任务", "minutes": 10}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        plan_id = created.json()["id"]
        rev = created.json()["revision"]

        updated = client.patch(
            f"/api/study-plans/{plan_id}",
            json={"title": "改后计划", "description": "补说明", "revision": rev},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200, updated.text
        data = updated.json()
        assert data["title"] == "改后计划"
        assert data["description"] == "补说明"
        assert data["revision"] == rev + 1

    def test_update_study_plan_revision_conflict_returns_409(self, client):
        token = _teacher_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={"title": "计划", "items": [{"title": "任务", "minutes": 10}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        plan_id = created.json()["id"]
        rev = created.json()["revision"]

        client.patch(
            f"/api/study-plans/{plan_id}",
            json={"title": "第一次改", "revision": rev},
            headers={"Authorization": f"Bearer {token}"},
        )
        conflict = client.patch(
            f"/api/study-plans/{plan_id}",
            json={"title": "第二次改", "revision": rev},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert conflict.status_code == 409

    def test_student_can_archive_own_plan_without_deleting_history(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={"title": "临时计划", "items": [{"title": "待移除任务", "minutes": 10}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        plan_id = created.json()["id"]

        archived = client.post(
            f"/api/study-plans/{plan_id}/archive",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
        active = client.get(
            "/api/students/2/study-plans?status=active",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert all(plan["id"] != plan_id for plan in active.json())
        all_plans = client.get(
            "/api/students/2/study-plans?status=",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert any(plan["id"] == plan_id and plan["status"] == "archived" for plan in all_plans.json())

    def test_student_can_carry_over_unfinished_plan_once(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "历史英语计划",
                "planned_date": (date.today() - timedelta(days=2)).isoformat(),
                "items": [
                    {"title": "已完成单元", "minutes": 10},
                    {"title": "继续复习", "minutes": 20},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        source_id = created.json()["id"]
        done = client.patch(
            f"/api/study-plan-items/{created.json()['items'][0]['id']}",
            json={"status": "done", "evidence_summary": "能复述单元重点"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert done.status_code == 200, done.text

        first = client.post(
            f"/api/study-plans/{source_id}/carry-over",
            headers={"Authorization": f"Bearer {token}"},
        )
        second = client.post(
            f"/api/study-plans/{source_id}/carry-over",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        assert first.json()["planned_date"] == date.today().isoformat()
        assert [item["title"] for item in first.json()["items"]] == ["继续复习"]
        all_plans = client.get(
            "/api/students/2/study-plans?status=",
            headers={"Authorization": f"Bearer {token}"},
        )
        statuses = {plan["id"]: plan["status"] for plan in all_plans.json()}
        assert statuses[source_id] == "archived"

    def test_create_study_plan_defaults_date_to_today(self, client):
        """创建计划未传 planned_date 时默认今天，避免计划页出现无日期或虚假逾期。"""
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={"title": "默认日期计划", "items": [{"title": "背单词", "minutes": 20}]},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert created.status_code == 200, created.text
        data = created.json()
        assert data["planned_date"] == date.today().isoformat()
        assert data["is_overdue"] is False
        item_id = data["items"][0]["id"]
        done = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done", "evidence_summary": "背出了不规则动词过去式"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert done.status_code == 200, done.text

    def test_active_past_plan_is_marked_overdue(self, client):
        token = _teacher_token(client)
        recent_past_date = (date.today() - timedelta(days=2)).isoformat()
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "逾期计划",
                "planned_date": recent_past_date,
                "items": [{"title": "补做旧计划", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        data = created.json()
        assert data["is_overdue"] is True
        assert data["overdue_days"] > 0
        assert "已逾期" in data["reminder_message"]
        assert "补做旧计划" in data["reminder_message"]

    def test_very_old_active_plan_is_auto_archived_and_hidden_from_active_list(self, client):
        """超长期未处理的旧计划应自动归档，避免污染学生的进行中计划。"""
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "过期很久的计划",
                "planned_date": "2025-01-06",
                "items": [{"title": "旧任务", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        plan_id = created.json()["id"]

        active = client.get("/api/students/2/study-plans?status=active", headers={"Authorization": f"Bearer {token}"})
        assert active.status_code == 200
        assert all(plan["id"] != plan_id for plan in active.json())

        all_plans = client.get("/api/students/2/study-plans?status=", headers={"Authorization": f"Bearer {token}"})
        assert all_plans.status_code == 200
        archived = next(plan for plan in all_plans.json() if plan["id"] == plan_id)
        assert archived["status"] == "archived"
        assert archived["is_overdue"] is False
        assert archived["overdue_days"] == 0
        assert archived["reminder_message"] is None

    def test_completed_past_plan_is_not_overdue(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "已收尾旧计划",
                "planned_date": "2000-01-01",
                "items": [{"title": "收尾任务", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        item_id = created.json()["items"][0]["id"]

        updated = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done", "evidence_summary": "背出了不规则动词过去式"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200, updated.text

        listed = client.get("/api/students/2/study-plans?status=completed", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        plan = next(item for item in listed.json() if item["id"] == created.json()["id"])
        assert plan["is_overdue"] is False
        assert plan["overdue_days"] == 0
        assert plan["reminder_message"] is None

    def test_student_can_complete_plan_item(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "自主管理计划",
                "items": [{"title": "背不规则动词", "minutes": 15}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        item_id = created.json()["items"][0]["id"]

        updated = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done", "evidence_summary": "背出了不规则动词过去式"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "done"
        assert updated.json()["completed_at"] is not None

        feedback = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"})
        assert feedback.status_code == 200
        assert any("完成学习计划任务「背不规则动词」" in item["content"] for item in feedback.json())

        client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done", "evidence_summary": "背出了不规则动词过去式"},
            headers={"Authorization": f"Bearer {token}"},
        )
        feedback_again = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"})
        matching = [item for item in feedback_again.json() if "完成学习计划任务「背不规则动词」" in item["content"]]
        assert len(matching) == 1

    def test_skipped_plan_item_records_review_feedback(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "跳过反馈计划",
                "items": [{"title": "整理错题原因", "target": "写出卡住点", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        item_id = created.json()["items"][0]["id"]

        updated = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "skipped"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "skipped"

        feedback = client.get("/api/students/2/feedback", headers={"Authorization": f"Bearer {token}"})
        assert feedback.status_code == 200
        assert any("跳过学习计划任务「整理错题原因」" in item["content"] for item in feedback.json())

    def test_due_study_plan_reminders_list_today_and_overdue(self, client):
        token = _teacher_token(client)
        today = date.today().isoformat()
        recent_past_date = (date.today() - timedelta(days=2)).isoformat()
        plans = [
            {
                "title": "今天英语计划",
                "planned_date": today,
                "items": [{"title": "背 10 个单词", "minutes": 10}, {"title": "复盘错题", "minutes": 15}],
            },
            {
                "title": "逾期数学计划",
                "planned_date": recent_past_date,
                "items": [{"title": "补做计算题", "minutes": 20}],
            },
            {
                "title": "未来计划",
                "planned_date": "2999-01-01",
                "items": [{"title": "以后再做", "minutes": 20}],
            },
        ]
        for payload in plans:
            resp = client.post("/api/students/2/study-plans", json=payload, headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200, resp.text

        resp = client.get("/api/study-plan-reminders/due", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        titles = {item["title"] for item in data}
        assert "今天英语计划" in titles
        assert "逾期数学计划" in titles
        assert "未来计划" not in titles
        today_item = next(item for item in data if item["title"] == "今天英语计划")
        assert today_item["todo_count"] == 2
        assert today_item["todo_minutes"] == 25
        assert "今天计划" in today_item["reminder_message"]
        overdue_item = next(item for item in data if item["title"] == "逾期数学计划")
        assert overdue_item["is_overdue"] is True
        assert "已逾期" in overdue_item["reminder_message"]

    def test_due_study_plan_reminders_follow_student_access_boundary(self, client):
        token = _student_token(client)
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "学生自己的今日计划",
                "planned_date": date.today().isoformat(),
                "items": [{"title": "先做一题", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text

        own = client.get("/api/study-plan-reminders/due", headers={"Authorization": f"Bearer {token}"})
        blocked = client.get("/api/study-plan-reminders/due?student_id=1", headers={"Authorization": f"Bearer {token}"})

        assert own.status_code == 200
        assert any(item["title"] == "学生自己的今日计划" for item in own.json())
        assert blocked.status_code == 403


class TestStudyPlanItemEvidenceGate:
    """P0 门禁：PATCH done 必须带学生作答证据（共享 service 校验，空白证据 422）。"""

    def _create_item(self, client, token):
        created = client.post(
            "/api/students/2/study-plans",
            json={
                "title": "门禁测试计划",
                "items": [{"title": "背古诗", "minutes": 10}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200, created.text
        return created.json()["items"][0]["id"]

    def test_done_without_evidence_is_422_and_state_unchanged(self, client):
        token = _student_token(client)
        item_id = self._create_item(client, token)
        r = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422
        # 状态未变：仍可查到 todo
        items = client.get("/api/students/2/study-plans?status=active", headers={"Authorization": f"Bearer {token}"}).json()
        it = next(it for plan in items for it in plan["items"] if it["id"] == item_id)
        assert it["status"] == "todo"

    def test_done_with_blank_evidence_is_422(self, client):
        token = _student_token(client)
        item_id = self._create_item(client, token)
        for blank in ("", "   \n  "):
            r = client.patch(
                f"/api/study-plan-items/{item_id}",
                json={"status": "done", "evidence_summary": blank},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 422, r.text

    def test_done_with_evidence_writes_attempt_and_feedback(self, client, db):
        token = _student_token(client)
        item_id = self._create_item(client, token)
        r = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "done", "evidence_summary": "背出了全诗并说出主旨"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"
        from app.models.p2 import LearningFeedback, StudyPlanItemAttempt
        attempt = db.query(StudyPlanItemAttempt).filter_by(plan_item_id=item_id).first()
        assert attempt is not None
        assert attempt.assessment == "passed"
        assert attempt.evidence_summary == "背出了全诗并说出主旨"
        assert db.query(LearningFeedback).filter_by(student_id=2).count() >= 1

    def test_skip_still_works_without_evidence(self, client):
        """skip 不受证据门禁影响。"""
        token = _student_token(client)
        item_id = self._create_item(client, token)
        r = client.patch(
            f"/api/study-plan-items/{item_id}",
            json={"status": "skipped"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "skipped"


class TestAttributesAPI:
    """属性面板接口 + 权限。"""

    def test_parent_init_attributes(self, client):
        token = _teacher_token(client)
        r = client.post(
            "/api/students/2/attributes/init",
            json={"exam_scores": {"chinese": 85, "math": 90, "english": 78, "pe": 80}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        snap = r.json()["snapshot"]
        assert snap["chinese"] == 85
        assert snap["mastered_count"] == 0

    def test_student_cannot_init_attributes(self, client):
        token = _student_token(client)
        r = client.post("/api/students/2/attributes/init", json={"exam_scores": {"math": 100}}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_get_attributes_after_init(self, client):
        token = _teacher_token(client)
        client.post("/api/students/2/attributes/init", json={"exam_scores": {"math": 70}}, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/students/2/attributes", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["current"] is not None

    def test_get_attribute_history(self, client):
        token = _teacher_token(client)
        client.post("/api/students/2/attributes/init", json={"exam_scores": {"math": 70}}, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/students/2/attributes?history=true", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json()["history"], list)


class TestProfileOnboardingAPI:
    """冷启动画像补全接口。"""

    def test_old_user_without_profile_needs_onboarding(self, client, db):
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()

        token = _student_token(client)
        r = client.get("/api/students/2/profile/summary", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200
        data = r.json()
        assert data["student_id"] == 2
        assert data["needs_onboarding"] is True
        assert "grade" in data["missing_fields"]
        assert "weak_subjects" in data["missing_fields"]

    def test_student_can_save_own_onboarding_profile(self, client):
        token = _student_token(client)
        r = client.post(
            "/api/students/2/profile/onboarding",
            json={
                "grade": "八年级",
                "semester": "上册",
                "weak_subjects": ["英语"],
                "recent_scores": {"english": 72},
                "study_preferences": {"preferred_time": "下午", "session_minutes": 25},
                "interests": ["篮球"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["needs_onboarding"] is False
        assert data["summary"]["grade"] == "八年级"
        assert data["summary"]["weak_subjects"] == ["英语"]
        assert "篮球" in data["summary"]["interests"]

    def test_cold_start_minimal_fields_completes_onboarding(self, client, db):
        """冷启动只问年级+薄弱科目：只存这两项即 needs_onboarding=false（学期/偏好不算冷启动范围）。"""
        db.query(StudentAttribute).filter(StudentAttribute.student_id == 2).delete(synchronize_session=False)
        db.commit()
        token = _student_token(client)
        r = client.post(
            "/api/students/2/profile/onboarding",
            json={"grade": "八年级", "weak_subjects": ["数学"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["needs_onboarding"] is False
        assert data["summary"]["grade"] == "八年级"

    def test_parent_can_add_school_but_interest_waits_for_student(self, client):
        token = _teacher_token(client)
        r = client.post(
            "/api/students/2/profile/onboarding",
            json={"school": "示例学校", "district": "苏州工业园区", "interests": ["冷启动建议兴趣-天文"]},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["summary"]["school"] == "示例学校"

        listed = client.get("/api/students/2/interests", headers={"Authorization": f"Bearer {token}"})
        pending = [item for item in listed.json() if item["tag"] == "冷启动建议兴趣-天文"]
        assert pending
        assert pending[-1]["approved"] is False

    def test_student_cannot_save_other_student_profile(self, client):
        token = _student_token(client)
        r = client.post(
            "/api/students/1/profile/onboarding",
            json={"grade": "八年级"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code in {403, 404}


class TestRecommendationAPI:
    """推荐接口。"""

    def test_get_recommendation_boundary_defaults(self, client):
        token = _teacher_token(client)
        r = client.get("/api/students/2/recommendation-boundary", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["allowed_platforms"] == ["bilibili"]
        assert r.json()["daily_limit"] == 3

    def test_parent_can_update_recommendation_boundary(self, client):
        token = _teacher_token(client)
        r = client.put(
            "/api/students/2/recommendation-boundary",
            json={
                "allowed_platforms": ["bilibili"],
                "blocked_keywords": ["游戏直播"],
                "daily_limit": 2,
                "allow_entertainment_interests": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["blocked_keywords"] == ["游戏直播"]
        assert r.json()["daily_limit"] == 2

    def test_student_cannot_update_recommendation_boundary(self, client):
        token = _student_token(client)
        r = client.put(
            "/api/students/2/recommendation-boundary",
            json={
                "allowed_platforms": ["bilibili"],
                "blocked_keywords": [],
                "daily_limit": 1,
                "allow_entertainment_interests": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_list_recommendations(self, client):
        token = _teacher_token(client)
        r = client.get("/api/students/2/recommendations", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_mark_clicked_not_found(self, client):
        token = _teacher_token(client)
        r = client.post("/api/recommendations/99999/click", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    def test_bound_parent_can_mark_recommendation_clicked(self, client, db):
        rec = recommendation.save_recommendation(db, 2, "绑定学生推荐", "https://example.com/bound-rec")

        token = _teacher_token(client)
        r = client.post(f"/api/recommendations/{rec.id}/click", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200
        assert r.json() == {"clicked": True}

    def test_mark_clicked_requires_recommendation_student_access(self, client, db):
        other_student = User(
            username="other-student-for-rec-click",
            password_hash="unused",
            role="student",
            display_name="未绑定学生",
        )
        db.add(other_student)
        db.commit()
        db.refresh(other_student)
        rec = recommendation.save_recommendation(db, other_student.id, "未绑定推荐", "https://example.com/rec")

        token = _teacher_token(client)
        r = client.post(f"/api/recommendations/{rec.id}/click", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 404
