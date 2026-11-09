"""每日学习记录只读 API 集成测试。

覆盖 spec 5.1 权限 + spec 12.1 查询：
- 学生只能读自己；家长只能读绑定学生
- 单日查询命中 -> 200；无记录 -> 404
- 日期范围查询 -> 数组，按日期升序
- 范围内无记录 -> 空数组
- 权限隔离：学生传别人 id -> 403；家长传未绑定学生 -> 403
- 不存在任意写接口（POST/PATCH/DELETE -> 405）
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.features.growth import daily_record_service as daily_learning_record_service
from app.config import settings


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestDailyRecordSingleDay:
    """单日查询。"""

    def test_student_reads_own_record(self, client, db):
        """学生读自己当日记录 -> 200。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        db.commit()
        token = _student_token(client)
        r = client.get("/api/daily-records?date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["student_id"] == 2
        assert body["record_date"] == "2026-07-17"
        assert body["generation_status"] == "pending"
        assert "facts_snapshot" in body

    def test_student_missing_day_404(self, client):
        """学生查无记录的日期 -> 404，不自动创建。"""
        token = _student_token(client)
        r = client.get("/api/daily-records?date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    def test_parent_reads_bound_student(self, client, db):
        """家长读绑定学生当日记录 -> 200。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        db.commit()
        token = _teacher_token(client)
        r = client.get("/api/daily-records?student_id=2&date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["student_id"] == 2

    def test_student_cannot_read_other(self, client, db):
        """学生传别人 student_id -> 403。"""
        from app.models.user import User
        from app.utils.security import hash_password

        other = User(username="other_student3", password_hash=hash_password("x"), role="student", display_name="另一学生")
        db.add(other)
        db.commit()
        token = _student_token(client)
        r = client.get("/api/daily-records?student_id=9999&date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_parent_unbound_student_403(self, client):
        """家长传未绑定学生 -> 403。"""
        token = _teacher_token(client)
        r = client.get("/api/daily-records?student_id=9999&date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_parent_missing_student_id_400(self, client):
        """家长不传 student_id -> 400。"""
        token = _teacher_token(client)
        r = client.get("/api/daily-records?date=2026-07-17", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400


class TestDailyRecordRange:
    """日期范围查询。"""

    def test_range_returns_sorted_array(self, client, db):
        """范围查询 -> 按日期升序数组。"""
        for d in (date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)):
            daily_learning_record_service.get_or_create(db, student_id=2, record_date=d)
        db.commit()
        token = _teacher_token(client)
        r = client.get(
            "/api/daily-records?student_id=2&start_date=2026-07-16&end_date=2026-07-17",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert [x["record_date"] for x in data] == ["2026-07-16", "2026-07-17"]

    def test_range_empty_returns_empty_array(self, client):
        """范围内无记录 -> 空数组（不是 404）。"""
        token = _teacher_token(client)
        r = client.get(
            "/api/daily-records?student_id=2&start_date=2026-07-10&end_date=2026-07-12",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_student_range_omits_student_id(self, client, db):
        """学生范围查询可不传 student_id（默认自己）。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        db.commit()
        token = _student_token(client)
        r = client.get(
            "/api/daily-records?start_date=2026-07-17&end_date=2026-07-17",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["student_id"] == 2


class TestNoWriteEndpoints:
    """除受控 refresh 外，不存在任意写接口。"""

    def test_post_not_allowed(self, client):
        token = _student_token(client)
        r = client.post("/api/daily-records", json={}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 405

    def test_patch_not_allowed(self, client):
        token = _student_token(client)
        r = client.patch("/api/daily-records/1", json={}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 405

    def test_delete_not_allowed(self, client):
        token = _student_token(client)
        r = client.delete("/api/daily-records/1", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 405


class TestDailyRecordRefresh:
    """Today 使用统一 refresh owner 刷新当日记录。"""

    def test_student_refresh_uses_server_local_date(self, client, db, monkeypatch):
        called: dict[str, object] = {}

        async def fake_refresh(db_arg, student_id, record_date, *, now=None):
            called.update(student_id=student_id, record_date=record_date, now=now)
            return daily_learning_record_service.get_or_create(db_arg, student_id, record_date)

        monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
        token = _student_token(client)
        response = client.post(
            "/api/daily-records/refresh?date=1999-01-01&timezone=UTC",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        assert called["student_id"] == 2
        assert called["record_date"] == datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()
        assert response.json()["student_id"] == 2

    def test_refresh_reuses_access_permission(self, client, monkeypatch):
        called = False

        async def fake_refresh(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("越权请求不应触发 refresh")

        monkeypatch.setattr(daily_learning_record_service, "refresh", fake_refresh)
        token = _teacher_token(client)
        response = client.post(
            "/api/daily-records/refresh?student_id=9999",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert called is False


class TestResponseShape:
    """响应字段覆盖 spec 3.1 契约。"""

    def test_record_item_contains_all_contract_fields(self, client, db):
        """返回项包含 spec 3.1 全部字段。"""
        daily_learning_record_service.get_or_create(db, student_id=2, record_date=date(2026, 7, 17))
        db.commit()
        token = _student_token(client)
        body = client.get("/api/daily-records?date=2026-07-17", headers={"Authorization": f"Bearer {token}"}).json()
        for field in (
            "id",
            "student_id",
            "record_date",
            "facts_snapshot",
            "summary_text",
            "evidence_hash",
            "generation_status",
            "summary_source",
            "checkin_status",
            "checkin_response",
            "checked_in_at",
            "generated_at",
            "finalized_at",
            "created_at",
            "updated_at",
        ):
            assert field in body, f"缺少契约字段 {field}"
