"""计划草案确认接口测试：创建、跨学生拒绝、旧 revision 拒绝。"""

from app.models import StudyPlanDraft


def _make_draft(db, student_id=2, revision=1, status="pending", draft_data=None):
    d = StudyPlanDraft(
        student_id=student_id,
        draft_data=draft_data or {"title": "数学复习", "items": [{"title": "复习概念", "minutes": 20}]},
        revision=revision,
        status=status,
    )
    db.add(d)
    db.flush()
    return d


class TestPlanDraftConfirm:
    def test_confirm_creates_plan(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db)
        r = client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["plan_id"] is not None

    def test_confirm_cross_student_rejected(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db, student_id=999)  # 别人的草案
        r = client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400  # 草案不存在或无权访问

    def test_confirm_old_revision_rejected(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db, revision=1)
        r = client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    def test_confirm_duplicate_returns_same_plan_id(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db)
        r1 = client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        r2 = client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["plan_id"] == r2.json()["plan_id"]


class TestPlanDraftGet:
    def test_get_pending_draft(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db)
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending"
        assert body["created_plan_id"] is None
        assert body["title"] == "数学复习"

    def test_get_created_draft_returns_created_plan_id(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db)
        # 先确认创建
        client.post(
            f"/api/study-plan-drafts/{draft.id}/confirm",
            json={"revision": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 再 GET，应返回 status=created + created_plan_id（前端据此不恢复卡片）
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "created"
        assert body["created_plan_id"] is not None

    def test_get_draft_cross_student_404(self, client, db):
        token = client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]
        draft = _make_draft(db, student_id=999)  # 别人的草案
        r = client.get(
            f"/api/study-plan-drafts/{draft.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404
