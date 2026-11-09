"""学生主动报进度接口测试。

覆盖：
- 非学生 -> 403
- 当日无摘要 -> 400
- 未绑定家长 -> 400
- 正常发送（iLink 通道）-> 200，调用 send_ilink_text
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import settings
from app.features.growth import daily_record_service
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WechatAccount,
    WechatGuardianStudentContext,
)


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _today():
    return datetime.now(ZoneInfo(settings.WECHAT_TIMEZONE)).date()


def _seed_record_with_summary(db, summary: str) -> None:
    record = daily_record_service.get_or_create(db, student_id=2, record_date=_today())
    record.summary_text = summary
    record.facts_snapshot = {
        "evidence": [{"tier": "self_reported", "title": "数学练习"}],
        "pending_tasks": [],
        "self_reported_duration_minutes": 30,
    }
    db.commit()


def _seed_ilink_binding(db) -> None:
    """建一条 teacher(1) -> student(2) 的 iLink 微信绑定。"""
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        openid="ilink_user_test",
        provider_account_id="pa_test",
        status="active",
        bound_at=datetime.now(),
    )
    db.add(account)
    db.flush()
    db.add(
        WechatGuardianStudentContext(
            account_id=account.id,
            student_id=2,
            push_time="20:00",
            status="active",
        )
    )
    db.commit()


class TestReportProgress:
    def test_not_student_403(self, client: TestClient):
        token = _teacher_token(client)
        r = client.post(
            "/api/channels/wechat/report-progress",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text

    def test_no_record_400(self, client: TestClient):
        token = _student_token(client)
        r = client.post(
            "/api/channels/wechat/report-progress",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, r.text
        assert "学习记录" in r.json()["detail"]

    def test_placeholder_summary_no_facts_400(self, client: TestClient, db):
        """占位摘要但无真实学习事实时拒绝发送（不把占位文本发给家长）。"""
        record = daily_record_service.get_or_create(db, student_id=2, record_date=_today())
        record.summary_text = "今天暂时没有新的学习记录。"
        record.facts_snapshot = {
            "evidence": [],
            "pending_tasks": [],
            "self_reported_duration_minutes": 0,
        }
        db.commit()
        _seed_ilink_binding(db)
        token = _student_token(client)
        r = client.post(
            "/api/channels/wechat/report-progress",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, r.text
        assert "学完再来报" in r.json()["detail"]

    def test_no_binding_400(self, client: TestClient, db):
        _seed_record_with_summary(db, "今天学习了数学，时长 30 分钟。")
        token = _student_token(client)
        r = client.post(
            "/api/channels/wechat/report-progress",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, r.text
        assert "绑定" in r.json()["detail"]

    def test_send_success_ilink(self, client: TestClient, db):
        _seed_record_with_summary(db, "今天学习了数学，时长 30 分钟。")
        _seed_ilink_binding(db)
        token = _student_token(client)
        with patch(
            "app.features.wechat.report_progress.messaging.send_ilink_text"
        ) as mock_send:
            r = client.post(
                "/api/channels/wechat/report-progress",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent"] == 1
        assert body["failed"] == 0
        assert mock_send.called
        args = mock_send.call_args.args
        assert args[0] == "pa_test"
        assert args[1] == "ilink_user_test"
        assert "今天学习了数学" in args[2]
