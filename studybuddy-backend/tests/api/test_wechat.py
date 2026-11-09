from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import reveal_secret, settings
from app.database import engine
from app.models.notification import Notification
from app.models.teacher_student import TeacherStudent
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    WechatAccount,
    WechatBindSession,
    WechatGuardianStudentContext,
)
from app.features.wechat import accounts, guardian as wechat_guardian, inbound
from app.models.user import User
from app.utils.security import hash_password


def _student_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "student", "password": "student123"}).json()["access_token"]


def _teacher_token(client: TestClient) -> str:
    return client.post("/auth/login", json={"username": "teacher", "password": "teacher123"}).json()["access_token"]


def _signature(token: str, timestamp: str, nonce: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()


def _text_message(openid: str, content: str) -> str:
    return f"""
<xml>
  <ToUserName><![CDATA[studybuddy]]></ToUserName>
  <FromUserName><![CDATA[{openid}]]></FromUserName>
  <CreateTime>1783500000</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[{content}]]></Content>
  <MsgId>10001</MsgId>
</xml>
""".strip()


def _response_content(xml_text: str) -> str:
    assert "<Content><![CDATA[" in xml_text
    return xml_text.split("<Content><![CDATA[", 1)[1].split("]]></Content>", 1)[0]


def _create_official_bind_session(db: Session, username: str) -> WechatBindSession:
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return accounts.create_bind_session(
        db, user, channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT
    )


def _add_shared_bot_account(db: Session, provider_account_id: str = "shared-bot@im.bot") -> None:
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
        WechatAccount.status == "active",
    ).update({WechatAccount.status: "unbound"}, synchronize_session=False)
    db.add(
        WechatAccount(
            user_id=1,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=provider_account_id,
            openid="existing-parent@im.wechat",
            status="active",
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()


def setup_module() -> None:
    WechatBindSession.__table__.create(bind=engine, checkfirst=True)
    WechatAccount.__table__.create(bind=engine, checkfirst=True)
    WechatGuardianStudentContext.__table__.create(bind=engine, checkfirst=True)


def test_create_and_poll_bind_session(client: TestClient, db: Session, monkeypatch) -> None:
    class _CreateResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "qr_value": "https://example.test/connect-qr",
                "session_id": "provider-session-new",
            }

    class _PollResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "qr_value": "https://example.test/connect-qr",
                "status": "confirmed",
                "provider_account_id": "bot-new@im.bot",
                "ilink_user_id": "student-scan@im.wechat",
            }

    monkeypatch.setattr(accounts.httpx, "post", lambda *_args, **_kwargs: _CreateResponse())
    monkeypatch.setattr(accounts.httpx, "get", lambda *_args, **_kwargs: _PollResponse())
    token = _student_token(client)

    created = client.post("/api/channels/wechat/bind-sessions", headers={"Authorization": f"Bearer {token}"})

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["bind_code"].startswith("W")
    assert payload["qr_value"] == "https://example.test/connect-qr"
    assert payload["status"] == "pending"
    session = db.get(WechatBindSession, payload["id"])
    assert session is not None
    assert session.provider_session_id == "provider-session-new"

    polled = client.get(
        f"/api/channels/wechat/bind-sessions/{payload['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert polled.status_code == 200
    assert polled.json()["bind_code"] == payload["bind_code"]
    assert polled.json()["status"] == "pending"
    db.refresh(session)
    assert session.provider_account_id == "bot-new@im.bot"
    assert session.wechat_openid == "student-scan@im.wechat"
    assert accounts.get_active_account(
        db, session.user_id, channel=WECHAT_CHANNEL_ILINK_BOT
    ) is None


def test_create_account_bind_session_returns_503_when_bot_service_is_unavailable(
    client: TestClient, monkeypatch
) -> None:
    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(accounts.httpx, "post", unavailable)

    response = client.post(
        "/api/channels/wechat/bind-sessions",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "微信连接服务暂不可用，请稍后再试"


def test_create_account_bind_session_requests_new_authorization(
    client: TestClient, db: Session, monkeypatch
) -> None:
    _add_shared_bot_account(db)
    requested: list[str] = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "qr_value": "https://example.test/new-student-qr",
                "session_id": "new-student-authorization",
            }

    def create_authorization(url: str, **_kwargs):
        requested.append(url)
        return _Response()

    monkeypatch.setattr(accounts.httpx, "post", create_authorization)

    created = client.post(
        "/api/channels/wechat/bind-sessions",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert created.status_code == 200, created.text
    session = db.get(WechatBindSession, created.json()["id"])
    assert session is not None
    assert requested[0].endswith("/v1/authorizations")
    assert session.provider_account_id is None
    assert session.provider_session_id == "new-student-authorization"
    assert session.qr_value == "https://example.test/new-student-qr"


def test_shared_bot_bind_code_accepts_the_current_scanner_identity(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret", raising=False)
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="",
    )
    session.provider_account_id = "shared-bot@im.bot"
    session.provider_session_id = None
    session.wechat_openid = None
    db.commit()

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "student-new@im.wechat",
            "content": session.bind_code,
        },
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "绑定成功"
    db.refresh(session)
    assert session.status == "bound"
    assert session.wechat_openid == "student-new@im.wechat"


def test_student_can_create_guardian_invitation(client: TestClient, db: Session, monkeypatch) -> None:
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "guardian-invitation-api",
                "qr_value": "https://example.test/guardian-invitation-api",
            }

    monkeypatch.setattr(accounts.httpx, "post", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(accounts.httpx, "get", lambda *args, **kwargs: _Response())

    created = client.post(
        "/api/channels/wechat/guardian-invitations",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert created.status_code == 200, created.text
    session = db.get(WechatBindSession, created.json()["id"])
    assert session is not None
    assert session.user_id is None
    assert session.invited_by_user_id == 2

    polled = client.get(
        f"/api/channels/wechat/bind-sessions/{session.id}",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )
    assert polled.status_code == 200


def test_teacher_cannot_create_guardian_invitation(client: TestClient) -> None:
    response = client.post(
        "/api/channels/wechat/guardian-invitations",
        headers={"Authorization": f"Bearer {_teacher_token(client)}"},
    )

    assert response.status_code == 403


def test_bound_guardian_can_bind_second_student_by_sending_invitation_code(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    guardian = db.get(User, 1)
    second_student = User(
        username="guardian-api-second-student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="第二个学生",
    )
    db.add(second_student)
    db.flush()
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot-second-child@im.bot",
        openid="guardian-second-child@im.wechat",
        active_identity_key=accounts.build_active_identity_key(
            WECHAT_CHANNEL_ILINK_BOT,
            "shared-bot-second-child@im.bot",
            "guardian-second-child@im.wechat",
        ),
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()
    invitation = accounts.create_guardian_invitation(
        db,
        second_student,
        qr_value="https://example.test/guardian-api-second-child",
        provider_session_id="guardian-api-second-child",
    )
    invitation.provider_account_id = account.provider_account_id
    invitation.wechat_openid = account.openid
    db.commit()

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": account.provider_account_id,
            "ilink_user_id": account.openid,
            "content": invitation.bind_code,
        },
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "绑定成功"
    assert db.get(TeacherStudent, (guardian.id, second_student.id)) is not None


def test_guardian_first_bind_only_asks_for_push_time_once(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    student = db.get(User, 2)
    invitation = accounts.create_guardian_invitation(
        db,
        student,
        qr_value="https://example.test/guardian-onboarding",
        provider_session_id="guardian-onboarding",
    )
    invitation.provider_account_id = "guardian-onboarding-bot@im.bot"
    invitation.wechat_openid = "guardian-onboarding@im.wechat"
    db.commit()

    bound = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": invitation.bind_code,
        },
    )

    prompt = (
        "你希望什么时候收到孩子的成长摘要？请选择下面一项，回复对应编号或时间。\n"
        "1. 晚上 20:00\n"
        "2. 晚上 21:00\n"
        "3. 保持默认（20:30）"
    )
    assert bound.json()["reply"] == prompt
    account = accounts.get_active_account_by_openid(
        db,
        invitation.wechat_openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=invitation.provider_account_id,
    )
    context = (
        db.query(WechatGuardianStudentContext)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.student_id == student.id,
        )
        .one()
    )
    assert account.guardian_onboarding_status == "awaiting_push_time"
    assert account.guardian_default_push_time == "20:30"
    assert account.selected_student_id == student.id
    assert context.push_time == "20:30"

    selected = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": "2",
        },
    )
    repeated = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": "1",
        },
    )

    db.refresh(account)
    db.refresh(context)
    assert selected.json()["reply"] == "已将测试学生的成长摘要设置为每天 21:00 推送。"
    assert repeated.json()["reply"] != prompt
    assert account.guardian_onboarding_status == "completed"
    assert account.guardian_default_push_time == "21:00"
    assert context.push_time == "21:00"

    second_student = User(
        username="guardian-onboarding-second-student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="第二个学生",
    )
    db.add(second_student)
    db.flush()
    second_invitation = accounts.create_guardian_invitation(
        db,
        second_student,
        qr_value="https://example.test/guardian-onboarding-second",
        provider_session_id="guardian-onboarding-second",
    )
    second_invitation.provider_account_id = invitation.provider_account_id
    second_invitation.wechat_openid = invitation.wechat_openid
    db.commit()
    second_bound = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": second_invitation.provider_account_id,
            "ilink_user_id": second_invitation.wechat_openid,
            "content": second_invitation.bind_code,
        },
    )
    second_context = (
        db.query(WechatGuardianStudentContext)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.student_id == second_student.id,
        )
        .one()
    )
    assert second_bound.json()["reply"] == "绑定成功"
    assert second_context.push_time == "21:00"
    assert account.selected_student_id is None


def test_guardian_push_time_accepts_exact_time_text(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """家长回复精确时间文本（非编号）也能设置成功：文案承诺"回复对应编号或时间"。"""
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(
        wechat_guardian,
        "send_ilink_text",
        lambda _provider, _openid, content: content,
    )
    student = db.get(User, 2)
    invitation = accounts.create_guardian_invitation(
        db, student, qr_value="https://example.test/guardian-onboarding-time-text",
        provider_session_id="guardian-onboarding-time-text",
    )
    invitation.provider_account_id = "guardian-onboarding-time-text@im.bot"
    invitation.wechat_openid = "guardian-onboarding-time-text@im.wechat"
    db.commit()

    client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": invitation.bind_code,
        },
    )
    account = accounts.get_active_account_by_openid(
        db,
        invitation.wechat_openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=invitation.provider_account_id,
    )
    context = (
        db.query(WechatGuardianStudentContext)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.student_id == student.id,
        )
        .one()
    )
    assert account.guardian_onboarding_status == "awaiting_push_time"

    # 回复精确时间文本（等于 option 2）
    by_time = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": "21:00",
        },
    )
    db.refresh(account)
    db.refresh(context)
    assert by_time.json()["reply"] == "已将测试学生的成长摘要设置为每天 21:00 推送。"
    assert account.guardian_onboarding_status == "completed"
    assert account.guardian_default_push_time == "21:00"
    assert context.push_time == "21:00"


def test_guardian_push_time_rejects_invalid_text(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """回复非法时间文本：返回选项提示，状态不变。"""
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(
        wechat_guardian,
        "send_ilink_text",
        lambda _provider, _openid, content: content,
    )
    student = db.get(User, 2)
    invitation = accounts.create_guardian_invitation(
        db, student, qr_value="https://example.test/guardian-onboarding-invalid",
        provider_session_id="guardian-onboarding-invalid",
    )
    invitation.provider_account_id = "guardian-onboarding-invalid@im.bot"
    invitation.wechat_openid = "guardian-onboarding-invalid@im.wechat"
    db.commit()

    client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": invitation.provider_account_id,
            "ilink_user_id": invitation.wechat_openid,
            "content": invitation.bind_code,
        },
    )
    account = accounts.get_active_account_by_openid(
        db,
        invitation.wechat_openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=invitation.provider_account_id,
    )
    context = (
        db.query(WechatGuardianStudentContext)
        .filter(
            WechatGuardianStudentContext.account_id == account.id,
            WechatGuardianStudentContext.student_id == student.id,
        )
        .one()
    )

    prompt = (
        "你希望什么时候收到孩子的成长摘要？请选择下面一项，回复对应编号或时间。\n"
        "1. 晚上 20:00\n"
        "2. 晚上 21:00\n"
        "3. 保持默认（20:30）"
    )
    for bad in ("19:00", "abc", "2000"):
        resp = client.post(
            "/api/internal/channels/wechat/ilink/messages",
            headers={"X-Internal-Token": "internal-secret"},
            json={
                "provider_account_id": invitation.provider_account_id,
                "ilink_user_id": invitation.wechat_openid,
                "content": bad,
            },
        )
        # 非法输入：重新给出选项（可能带学生名前缀），设置不生效
        assert prompt in resp.json()["reply"]
    db.refresh(account)
    assert account.guardian_onboarding_status == "awaiting_push_time"
    assert account.guardian_default_push_time == "20:30"


def test_student_family_context_api_is_scoped_to_own_student(
    client: TestClient, db: Session, monkeypatch
) -> None:
    sent_messages: list[str] = []
    monkeypatch.setattr(
        wechat_guardian,
        "send_ilink_text",
        lambda _provider, _openid, content: sent_messages.append(content) or "success",
    )
    student = db.get(User, 2)
    other_student = User(
        username="family-context-other-student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="其他学生",
    )
    guardian = User(
        username="family-context-guardian",
        password_hash=hash_password("not-used"),
        role="teacher",
        display_name="测试家长",
        web_login_enabled=False,
    )
    db.add_all([other_student, guardian])
    db.flush()
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="family-context-bot@im.bot",
        openid="family-context-guardian@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        selected_student_id=student.id,
    )
    db.add(account)
    db.flush()
    db.add_all(
        [
            TeacherStudent(teacher_id=guardian.id, student_id=student.id),
            TeacherStudent(teacher_id=guardian.id, student_id=other_student.id),
            WechatGuardianStudentContext(
                account_id=account.id, student_id=student.id, push_time="20:30"
            ),
            WechatGuardianStudentContext(
                account_id=account.id, student_id=other_student.id, push_time="20:30"
            ),
        ]
    )
    db.add(
        Notification(
            recipient_id=guardian.id,
            student_id=student.id,
            title="今日成长摘要",
            content="今天完成了函数错题复盘。",
            notification_type="daily_growth_summary",
            source_type="growth_summary",
            source_id=student.id,
            dedupe_key="growth:daily:2026-07-12",
        )
    )
    db.commit()
    own_context = (
        db.query(WechatGuardianStudentContext)
        .filter(WechatGuardianStudentContext.student_id == student.id)
        .one()
    )
    other_context = (
        db.query(WechatGuardianStudentContext)
        .filter(WechatGuardianStudentContext.student_id == other_student.id)
        .one()
    )
    token = _student_token(client)

    listed = client.get(
        "/api/channels/wechat/guardian-contexts",
        headers={"Authorization": f"Bearer {token}"},
    )
    settings_response = client.get(
        "/api/channels/wechat/guardian-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    updated = client.patch(
        f"/api/channels/wechat/guardian-contexts/{own_context.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"push_time": "21:00", "paused": True},
    )
    forbidden = client.patch(
        f"/api/channels/wechat/guardian-contexts/{other_context.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"push_time": "20:00"},
    )
    invalid = client.patch(
        f"/api/channels/wechat/guardian-contexts/{own_context.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"push_time": "19:15"},
    )
    unbound = client.delete(
        f"/api/channels/wechat/guardian-contexts/{own_context.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert listed.status_code == 200
    assert settings_response.json() == {
        "push_time_options": ["20:00", "21:00"],
        "default_push_time": "20:30",
    }
    assert [item["id"] for item in listed.json()] == [own_context.id]
    assert listed.json()[0]["latest_summary_title"] == "今日成长摘要"
    assert listed.json()[0]["latest_summary_content"] == "今天完成了函数错题复盘。"
    assert updated.status_code == 200
    assert updated.json()["push_time"] == "21:00"
    assert updated.json()["paused"] is True
    assert forbidden.status_code == 404
    assert invalid.status_code == 400
    assert unbound.status_code == 204
    db.refresh(account)
    assert account.selected_student_id is None
    db.refresh(own_context)
    assert own_context.status == "unbound"
    assert db.get(TeacherStudent, (guardian.id, student.id)) is None
    assert db.get(TeacherStudent, (guardian.id, other_student.id)) is not None
    assert sent_messages == [
        "测试学生的成长摘要推送已暂停。",
        "已解除与测试学生的家庭陪伴绑定。",
    ]


def test_poll_bind_session_refreshes_ilink_authorization(
    client: TestClient, db: Session, monkeypatch
) -> None:
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "qr_value": "https://example.test/ilink-refreshed-qr",
                "status": "confirmed",
                "provider_account_id": "bot-refreshed@im.bot",
                "ilink_user_id": "scanner-refreshed@im.wechat",
            }

    monkeypatch.setattr(accounts.httpx, "get", lambda *args, **kwargs: _Response())
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-old-qr",
        provider_session_id="provider-session-refresh",
    )

    response = client.get(
        f"/api/channels/wechat/bind-sessions/{session.id}",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert response.status_code == 200
    assert response.json()["qr_value"] == "https://example.test/ilink-refreshed-qr"
    assert response.json()["status"] == "pending"
    db.refresh(session)
    assert session.status == "pending"
    assert session.provider_account_id == "bot-refreshed@im.bot"
    assert session.wechat_openid == "scanner-refreshed@im.wechat"
    assert accounts.get_active_account(
        db, student.id, channel=WECHAT_CHANNEL_ILINK_BOT
    ) is None


def test_poll_bind_session_stops_when_ilink_authorization_fails(
    client: TestClient, db: Session, monkeypatch
) -> None:
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "failed"}

    monkeypatch.setattr(accounts.httpx, "get", lambda *args, **kwargs: _Response())
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/failed-qr",
        provider_session_id="provider-session-failed",
    )

    response = client.get(
        f"/api/channels/wechat/bind-sessions/{session.id}",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "expired"


def test_poll_bind_session_checks_owner_before_provider_refresh(
    client: TestClient, db: Session, monkeypatch
) -> None:
    owner = User(
        username="wechat-session-other-owner",
        password_hash=hash_password("student123"),
        role="student",
    )
    db.add(owner)
    db.commit()
    session = accounts.create_bind_session(
        db,
        owner,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/private-qr",
        provider_session_id="private-provider-session",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("provider must not be called before ownership check")

    monkeypatch.setattr(accounts.httpx, "get", fail_if_called)

    response = client.get(
        f"/api/channels/wechat/bind-sessions/{session.id}",
        headers={"Authorization": f"Bearer {_student_token(client)}"},
    )

    assert response.status_code == 404


def test_ilink_internal_message_binds_existing_student(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret", raising=False)
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-internal-qr",
        provider_session_id="provider-session-internal",
    )
    session.provider_account_id = "bot-internal@im.bot"
    session.wechat_openid = "student-internal@im.wechat"
    db.commit()

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "bot-internal@im.bot",
            "ilink_user_id": "student-internal@im.wechat",
            "content": session.bind_code,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "绑定成功",
        "persist_credentials": True,
        "activate_user": True,
        "deactivate_user": False,
    }
    account = accounts.get_active_account(
        db, student.id, channel=WECHAT_CHANNEL_ILINK_BOT
    )
    assert account is not None
    assert account.provider_account_id == "bot-internal@im.bot"


def test_bound_ilink_student_can_invite_existing_parent(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setattr(
        settings,
        "WECHAT_PARENT_INVITATION_URL",
        "https://example.test/#/wechat-parent-bind",
        raising=False,
    )

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "provider-parent-invitation",
                "qr_value": "https://example.test/parent-qr",
                "status": "pending",
            }

    monkeypatch.setattr(accounts.httpx, "post", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(accounts.httpx, "get", lambda *args, **kwargs: _Response())
    db.add(
        WechatAccount(
            user_id=2,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
            openid="student-invite@im.wechat",
            status="active",
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "student-invite@im.wechat",
            "content": "邀请家长",
        },
    )

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply.startswith("测试家长：https://example.test/#/wechat-parent-bind?token=")
    scene = reply.rsplit("token=", 1)[1]

    invitation = client.get(f"/api/channels/wechat/parent-invitations/{scene}")

    assert invitation.status_code == 200
    assert invitation.json() == {
        "parent_name": "测试家长",
        "student_name": "测试学生",
        "bind_code": invitation.json()["bind_code"],
        "qr_value": "https://example.test/parent-qr",
        "status": "pending",
        "expires_at": invitation.json()["expires_at"],
    }


def test_bound_ilink_student_without_parent_relation_cannot_create_invitation(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    student = User(
        username="wechat-invite-no-parent",
        password_hash=hash_password("student123"),
        role="student",
        display_name="无家长学生",
    )
    db.add(student)
    db.flush()
    db.add(
        WechatAccount(
            user_id=student.id,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
            openid="student-no-parent@im.wechat",
            status="active",
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "student-no-parent@im.wechat",
            "content": "邀请家长",
        },
    )

    assert response.json()["reply"] == "当前没有已绑定家长"


def test_bound_student_message_schedules_shared_agent_without_immediate_reply(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    account = WechatAccount(
        user_id=2,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="student-agent@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()
    scheduled: list[tuple[int, str]] = []
    monkeypatch.setattr(
        inbound,
        "process_student_agent_message",
        lambda account_id, content: scheduled.append((account_id, content)),
        raising=False,
    )

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "student-agent@im.wechat",
            "content": "我最近总错什么",
        },
    )

    assert response.json()["reply"] == ""
    assert scheduled == [(account.id, "我最近总错什么")]


def test_bound_parent_plain_text_runs_guardian_agent(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-plain-text@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    db.add(
        WechatGuardianStudentContext(
            account_id=account.id,
            student_id=2,
            push_time="20:30",
        )
    )
    account.selected_student_id = 2
    db.commit()

    scheduled = []
    monkeypatch.setattr(
        "app.features.wechat.router.inbound.process_guardian_agent_message",
        lambda account_id, student_id, content: scheduled.append(
            (account_id, student_id, content)
        ),
        raising=False,
    )

    response = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "parent-plain-text@im.wechat",
            "content": "你好",
        },
    )

    assert response.json()["reply"] == ""
    assert scheduled == [(account.id, 2, "你好")]


def test_bound_ilink_parent_can_change_selected_student_push_time(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-command@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        reminder_times=["08:00"],
    )
    db.add(account)
    db.flush()
    context = WechatGuardianStudentContext(
        account_id=account.id,
        student_id=2,
        push_time="20:30",
    )
    db.add(context)
    db.commit()

    scheduled = []
    monkeypatch.setattr(
        "app.features.wechat.router.inbound.process_guardian_agent_message",
        lambda account_id, student_id, content: scheduled.append(
            (account_id, student_id, content)
        ),
        raising=False,
    )

    def send(content: str):
        return client.post(
            "/api/internal/channels/wechat/ilink/messages",
            headers={"X-Internal-Token": "internal-secret"},
            json={
                "provider_account_id": "shared-bot@im.bot",
                "ilink_user_id": "parent-command@im.wechat",
                "content": content,
            },
        )

    summary = send("今日学情")
    menu = send("修改推送时间")
    configured = send("1")

    assert summary.json()["reply"] == ""
    assert scheduled == [(account.id, 2, "今日学情")]
    assert menu.json()["reply"] == (
        "正在修改测试学生的成长摘要时间。\n"
        "你希望什么时候收到孩子的成长摘要？请选择下面一项，回复对应编号或时间。\n"
        "1. 晚上 20:00\n"
        "2. 晚上 21:00\n"
        "3. 保持默认（20:30）"
    )
    assert configured.json()["reply"] == "已将测试学生的成长摘要设置为每天 20:00 推送。"
    db.refresh(context)
    assert account.reminder_times == ["08:00"]
    assert context.push_time == "20:00"


def test_ilink_internal_accounts_returns_known_bot_with_active_users(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT
    ).update(
        {
            WechatAccount.status: "unbound",
            WechatAccount.provider_account_id: None,
        },
        synchronize_session=False,
    )
    db.commit()
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-restore-qr",
        provider_session_id="provider-session-restore",
    )
    session.provider_account_id = "bot-restore@im.bot"
    session.wechat_openid = "student-restore@im.wechat"
    db.commit()
    accounts.complete_bind_by_code(
        db,
        session.bind_code,
        "student-restore@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="bot-restore@im.bot",
    )
    _create_official_bind_session(db, "student")

    response = client.get(
        "/api/internal/channels/wechat/ilink/accounts",
        headers={"X-Internal-Token": "internal-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "provider_account_id": "bot-restore@im.bot",
                "ilink_user_ids": ["student-restore@im.wechat"],
            }
        ]
    }


def test_ilink_internal_accounts_keeps_shared_bot_when_no_user_is_active(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
    ).update({WechatAccount.provider_account_id: None}, synchronize_session=False)
    db.add(
        WechatAccount(
            user_id=2,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="bot-idle@im.bot",
            openid="former-user@im.wechat",
            status="unbound",
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()

    response = client.get(
        "/api/internal/channels/wechat/ilink/accounts",
        headers={"X-Internal-Token": "internal-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "provider_account_id": "bot-idle@im.bot",
                "ilink_user_ids": [],
            }
        ]
    }


def test_ilink_internal_accounts_groups_users_by_provider(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
    ).update(
        {
            WechatAccount.status: "unbound",
            WechatAccount.provider_account_id: None,
        },
        synchronize_session=False,
    )
    db.add_all(
        [
            WechatAccount(
                user_id=1,
                channel=WECHAT_CHANNEL_ILINK_BOT,
                provider_account_id="bot-a@im.bot",
                openid="user-a@im.wechat",
                status="active",
                bound_at=datetime.utcnow(),
            ),
            WechatAccount(
                user_id=2,
                channel=WECHAT_CHANNEL_ILINK_BOT,
                provider_account_id="bot-b@im.bot",
                openid="user-b@im.wechat",
                status="active",
                bound_at=datetime.utcnow(),
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/api/internal/channels/wechat/ilink/accounts",
        headers={"X-Internal-Token": "internal-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "provider_account_id": "bot-a@im.bot",
                "ilink_user_ids": ["user-a@im.wechat"],
            },
            {
                "provider_account_id": "bot-b@im.bot",
                "ilink_user_ids": ["user-b@im.wechat"],
            },
        ]
    }


def test_wechat_get_callback_validates_signature(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WECHAT_TOKEN", "test-token")
    timestamp = "1783500001"
    nonce = "abc"
    signature = _signature("test-token", timestamp, nonce)

    resp = client.get(
        "/api/channels/wechat/callback",
        params={"signature": signature, "timestamp": timestamp, "nonce": nonce, "echostr": "hello"},
    )

    assert resp.status_code == 200
    assert resp.text == "hello"


def test_wechat_post_text_bind_code_binds_account(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_TOKEN", "test-token")
    session = _create_official_bind_session(db, "student")
    timestamp = "1783500002"
    nonce = "nonce"
    signature = _signature("test-token", timestamp, nonce)

    resp = client.post(
        "/api/channels/wechat/callback",
        params={"signature": signature, "timestamp": timestamp, "nonce": nonce},
        content=_text_message("openid-from-wechat", session.bind_code),
        headers={"Content-Type": "application/xml"},
    )

    assert resp.status_code == 200, resp.text
    assert "绑定成功" in _response_content(resp.text)
    account = accounts.get_active_account_by_openid(
        db, "openid-from-wechat", channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT
    )
    assert account is not None


def test_bound_parent_can_query_today_and_configure_reminders(client: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WECHAT_TOKEN", "test-token")
    session = _create_official_bind_session(db, "teacher")
    signature = _signature("test-token", "1783500006", "nonce-parent-command")
    params = {"signature": signature, "timestamp": "1783500006", "nonce": "nonce-parent-command"}
    openid = "openid-parent-command"
    client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=_text_message(openid, session.bind_code),
        headers={"Content-Type": "application/xml"},
    )

    summary = client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=_text_message(openid, "今日学情"),
        headers={"Content-Type": "application/xml"},
    )
    configured = client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=_text_message(openid, "提醒 09:00 20:30"),
        headers={"Content-Type": "application/xml"},
    )

    assert "测试学生今日学情" in _response_content(summary.text)
    assert _response_content(configured.text) == "提醒时间已设置：09:00、20:30"
    account = db.query(WechatAccount).filter(WechatAccount.openid == openid, WechatAccount.status == "active").first()
    assert account is not None
    assert account.reminder_times == ["09:00", "20:30"]
    assert account.last_interacted_at is not None

    invalid = client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=_text_message(openid, "提醒 九点"),
        headers={"Content-Type": "application/xml"},
    )
    assert _response_content(invalid.text) == "提醒格式：提醒 09:00 20:30"
    db.refresh(account)
    assert account.reminder_times == ["09:00", "20:30"]

    previous_interaction = datetime.utcnow() - timedelta(days=3)
    account.last_interacted_at = previous_interaction
    db.commit()
    image_message = _text_message(openid, "").replace("<MsgType><![CDATA[text]]>", "<MsgType><![CDATA[image]]>")
    image_response = client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=image_message,
        headers={"Content-Type": "application/xml"},
    )
    assert _response_content(image_response.text) == "已收到。当前微信公众号先支持发送绑定码完成账号绑定。"
    db.refresh(account)
    assert account.last_interacted_at > previous_interaction

    closed = client.post(
        "/api/channels/wechat/callback",
        params=params,
        content=_text_message(openid, "关闭提醒"),
        headers={"Content-Type": "application/xml"},
    )
    assert _response_content(closed.text) == "学习提醒已关闭"
    db.refresh(account)
    assert account.reminder_times is None


def test_parent_bind_requires_existing_student_relation(client: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WECHAT_TOKEN", "test-token")
    teacher = User(
        username="wechat-parent-without-student",
        password_hash=hash_password("teacher123"),
        role="teacher",
        display_name="无学生家长",
    )
    db.add(teacher)
    db.commit()
    session = accounts.create_bind_session(
        db, teacher, channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT
    )
    signature = _signature("test-token", "1783500007", "nonce-parent-unbound")

    response = client.post(
        "/api/channels/wechat/callback",
        params={"signature": signature, "timestamp": "1783500007", "nonce": "nonce-parent-unbound"},
        content=_text_message("openid-parent-without-student", session.bind_code),
        headers={"Content-Type": "application/xml"},
    )

    assert _response_content(response.text) == "绑定失败：家长账号尚未绑定学生"


def test_unbind_wechat_account(client: TestClient, db: Session, monkeypatch) -> None:
    token = _student_token(client)
    revoked: list[tuple[str, dict[str, str]]] = []

    class _Response:
        def raise_for_status(self):
            return None

    def revoke_user(url: str, **kwargs):
        revoked.append((url, kwargs["headers"]))
        return _Response()

    monkeypatch.setattr(accounts.httpx, "delete", revoke_user)
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-unbind-qr",
        provider_session_id="provider-session-unbind",
    )
    session.provider_account_id = "bot-unbind@im.bot"
    session.wechat_openid = "student-unbind@im.wechat"
    db.commit()
    accounts.complete_bind_by_code(
        db,
        session.bind_code,
        "student-unbind@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="bot-unbind@im.bot",
    )

    resp = client.delete("/api/channels/wechat/account", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 204
    assert revoked == [
        (
            (
                f"{settings.WECHAT_BOT_SERVICE_URL}/v1/accounts/"
                "bot-unbind%40im.bot/users/student-unbind%40im.wechat"
            ),
            {"X-Internal-Token": reveal_secret(settings.WECHAT_BOT_INTERNAL_TOKEN)},
        )
    ]
    account = client.get("/api/channels/wechat/account", headers={"Authorization": f"Bearer {token}"})
    assert account.json()["bound"] is False


def test_failed_unbind_revocation_self_heals_on_next_inbound(
    client: TestClient, db: Session, monkeypatch
) -> None:
    token = _student_token(client)
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-revoke-retry-qr",
        provider_session_id="provider-session-revoke-retry",
    )
    session.provider_account_id = "bot-revoke-retry@im.bot"
    session.wechat_openid = "student-revoke-retry@im.wechat"
    db.commit()
    accounts.complete_bind_by_code(
        db,
        session.bind_code,
        "student-revoke-retry@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="bot-revoke-retry@im.bot",
    )
    monkeypatch.setattr(
        accounts,
        "revoke_ilink_user",
        lambda _provider_account_id, _user_id: (_ for _ in ()).throw(
            RuntimeError("bot unavailable")
        ),
    )

    unbound = client.delete(
        "/api/channels/wechat/account",
        headers={"Authorization": f"Bearer {token}"},
    )
    inbound = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": "bot-revoke-retry@im.bot",
            "ilink_user_id": "student-revoke-retry@im.wechat",
            "content": "仍在白名单",
        },
    )

    assert unbound.status_code == 204
    assert inbound.status_code == 200
    assert inbound.json() == {
        "reply": "绑定已解除",
        "persist_credentials": False,
        "activate_user": False,
        "deactivate_user": True,
    }


def test_valid_bind_code_reactivates_user_before_stale_revocation_cleanup(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "WECHAT_BOT_INTERNAL_TOKEN", "internal-secret")
    student = db.get(User, 2)
    provider_account_id = "shared-bot-rebind@im.bot"
    ilink_user_id = "student-rebind@im.wechat"
    db.query(WechatAccount).filter(
        WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
    ).update({WechatAccount.provider_account_id: None}, synchronize_session=False)
    db.add(
        WechatAccount(
            user_id=student.id,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=provider_account_id,
            openid=ilink_user_id,
            status="unbound",
            revocation_pending=True,
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()
    session = accounts.create_bind_session(
        db,
        student,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="",
    )
    session.provider_account_id = provider_account_id
    session.wechat_openid = ilink_user_id
    db.commit()

    inbound = client.post(
        "/api/internal/channels/wechat/ilink/messages",
        headers={"X-Internal-Token": "internal-secret"},
        json={
            "provider_account_id": provider_account_id,
            "ilink_user_id": ilink_user_id,
            "content": session.bind_code,
        },
    )

    assert inbound.status_code == 200
    assert inbound.json() == {
        "reply": "绑定成功",
        "persist_credentials": True,
        "activate_user": True,
        "deactivate_user": False,
    }
    assert accounts.get_active_account_by_openid(
        db,
        ilink_user_id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=provider_account_id,
    ) is not None


def test_wechat_callback_rejects_bad_signature(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "WECHAT_TOKEN", "test-token")

    resp = client.get(
        "/api/channels/wechat/callback",
        params={"signature": "bad", "timestamp": "1", "nonce": "2", "echostr": "hello"},
    )

    assert resp.status_code == 403
