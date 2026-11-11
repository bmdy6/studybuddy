from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import reveal_secret
from app.database import engine
from app.models.user import User
from app.models.p2 import LearningFeedback
from app.models.teacher_student import TeacherStudent
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WECHAT_CHANNEL_OFFICIAL_ACCOUNT,
    WechatAccount,
    WechatBindSession,
    WechatGuardianStudentContext,
)
from app.features.wechat import accounts, dispatch, guardian as wechat_guardian, inbound, messaging
from app.core.auth import access_service
from app.utils.security import hash_password


@pytest.fixture(scope="module", autouse=True)
def _wechat_tables() -> None:
    WechatBindSession.__table__.create(bind=engine, checkfirst=True)
    WechatAccount.__table__.create(bind=engine, checkfirst=True)


def _user(db: Session, username: str, role: str = "student") -> User:
    user = User(
        username=username,
        password_hash=hash_password("student123"),
        role=role,
        display_name=username,
    )
    db.add(user)
    db.flush()
    return user


def test_get_or_create_chat_session_reuses_mapping_and_recreates_deleted_session(
    db: Session,
) -> None:
    student = db.get(User, 2)
    account = WechatAccount(
        user_id=student.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="chat-session-student@im.wechat",
        active_identity_key=accounts.build_active_identity_key(
            WECHAT_CHANNEL_ILINK_BOT,
            "shared-bot@im.bot",
            "chat-session-student@im.wechat",
        ),
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()

    first = inbound.get_or_create_chat_session(db, account, student)
    second = inbound.get_or_create_chat_session(db, account, student)

    assert second.id == first.id
    assert first.title == "微信学习助手"

    first_id = first.id
    db.delete(first)
    db.commit()
    recreated = inbound.get_or_create_chat_session(db, account, student)

    assert recreated.id != first_id


def test_process_student_agent_message_uses_shared_session_and_sends_final(db: Session, monkeypatch) -> None:
    student = db.get(User, 2)
    account = WechatAccount(
        user_id=student.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="agent-final@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    async def fake_run_agent_turn(*_args, **_kwargs):
        return "你最近常错一次函数。"

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext, raising=False)
    monkeypatch.setattr(inbound.agent, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(
        inbound,
        "send_ilink_text",
        lambda bot, user, text: sent.append((bot, user, text)) or "success",
    )

    asyncio.run(inbound.process_student_agent_message(account.id, "我最近总错什么"))

    assert sent == [
        (
            "shared-bot@im.bot",
            "agent-final@im.wechat",
            "你最近常错一次函数。",
        )
    ]


def test_process_student_agent_message_sends_failure_when_agent_fails(db: Session, monkeypatch) -> None:
    account = WechatAccount(
        user_id=2,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="agent-failure@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    async def fail_agent(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    sent: list[str] = []
    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext)
    monkeypatch.setattr(inbound.agent, "run_agent_turn", fail_agent)
    monkeypatch.setattr(
        inbound,
        "send_ilink_text",
        lambda _bot, _user, text: sent.append(text) or "success",
    )

    asyncio.run(inbound.process_student_agent_message(account.id, "你好"))

    assert sent == ["这次没有处理成功，请再发一次。"]


def test_guardian_with_multiple_students_must_select_before_agent(db: Session) -> None:
    guardian = _user(db, "guardian_select", role="teacher")
    first = _user(db, "guardian_student_first")
    second = _user(db, "guardian_student_second")
    first.display_name = "小明"
    second.display_name = "小华"
    db.flush()
    access_service.bind_teacher_student(db, guardian.id, first.id)
    access_service.bind_teacher_student(db, guardian.id, second.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-select@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    db.add_all(
        [
            WechatGuardianStudentContext(account_id=account.id, student_id=first.id, push_time="20:30"),
            WechatGuardianStudentContext(account_id=account.id, student_id=second.id, push_time="20:30"),
        ]
    )
    db.commit()

    context, reply = wechat_guardian.resolve_guardian_message_target(db, account, "最近学得怎么样")

    assert context is None
    assert reply == "你想查看哪个孩子？\n1. 小明\n2. 小华"

    context, reply = wechat_guardian.resolve_guardian_message_target(db, account, "2")

    assert context is None
    assert reply == "已切换到小华，可以继续问我孩子最近的学习情况。"
    assert account.selected_student_id == second.id

    context, reply = wechat_guardian.resolve_guardian_message_target(db, account, "最近学得怎么样")

    assert context is not None
    assert context.student_id == second.id
    assert reply is None


def test_guardian_student_contexts_use_independent_chat_sessions(db: Session) -> None:
    guardian = _user(db, "guardian_sessions", role="teacher")
    first = _user(db, "guardian_session_first")
    second = _user(db, "guardian_session_second")
    access_service.bind_teacher_student(db, guardian.id, first.id)
    access_service.bind_teacher_student(db, guardian.id, second.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-sessions@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    contexts = [WechatGuardianStudentContext(account_id=account.id, student_id=student.id, push_time="20:30") for student in (first, second)]
    db.add_all(contexts)
    db.commit()

    first_session = wechat_guardian.get_or_create_guardian_chat_session(db, contexts[0], guardian)
    second_session = wechat_guardian.get_or_create_guardian_chat_session(db, contexts[1], guardian)

    assert first_session.id != second_session.id
    assert first_session.student_id == first.id
    assert second_session.student_id == second.id
    assert contexts[0].chat_session_id == first_session.id
    assert contexts[1].chat_session_id == second_session.id


def test_guardian_does_not_guess_between_students_with_same_name(db: Session) -> None:
    guardian = _user(db, "guardian_same_name", role="teacher")
    students = [
        _user(db, "guardian_same_name_first"),
        _user(db, "guardian_same_name_second"),
    ]
    for student in students:
        student.display_name = "小明"
        access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-same-name@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    db.add_all([WechatGuardianStudentContext(account_id=account.id, student_id=student.id, push_time="20:30") for student in students])
    db.commit()

    context, reply = wechat_guardian.resolve_guardian_message_target(db, account, "小明")

    assert context is None
    assert reply == "你想查看哪个孩子？\n1. 小明\n2. 小明"
    assert account.selected_student_id is None


def test_guardian_selects_student_before_changing_push_time(db: Session) -> None:
    guardian = _user(db, "guardian_push_multiple", role="teacher")
    first = _user(db, "guardian_push_first")
    second = _user(db, "guardian_push_second")
    first.display_name = "小明"
    second.display_name = "小华"
    for student in (first, second):
        access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-push-multiple@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        guardian_onboarding_status="completed",
        selected_student_id=None,
    )
    db.add(account)
    db.flush()
    contexts = [
        WechatGuardianStudentContext(
            account_id=account.id,
            student_id=student.id,
            push_time="20:30",
        )
        for student in (first, second)
    ]
    db.add_all(contexts)
    db.commit()

    select_student = wechat_guardian.handle_guardian_onboarding_choice(db, account, "修改推送时间")
    select_time = wechat_guardian.handle_guardian_onboarding_choice(db, account, "2")
    configured = wechat_guardian.handle_guardian_onboarding_choice(db, account, "1")

    assert select_student == "你想修改哪个孩子的成长摘要时间？\n1. 小明\n2. 小华"
    assert select_time == (
        "正在修改小华的成长摘要时间。\n"
        "你希望什么时候收到孩子的成长摘要？请选择下面一项，回复对应编号或时间。\n"
        "1. 晚上 20:00\n"
        "2. 晚上 21:00\n"
        "3. 保持默认（20:30）"
    )
    assert configured == "已将小华的成长摘要设置为每天 20:00 推送。"
    assert contexts[0].push_time == "20:30"
    assert contexts[1].push_time == "20:00"


def test_unbound_guardian_student_selection_is_invalidated(db: Session) -> None:
    guardian = _user(db, "guardian_unbound", role="teacher")
    student = _user(db, "guardian_unbound_student")
    access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-unbound@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        selected_student_id=student.id,
    )
    db.add(account)
    db.flush()
    db.add(
        WechatGuardianStudentContext(
            account_id=account.id,
            student_id=student.id,
            push_time="20:30",
            status="unbound",
        )
    )
    db.commit()

    context, reply = wechat_guardian.resolve_guardian_message_target(db, account, "孩子最近怎么样")

    assert context is None
    assert reply == "当前没有已绑定学生"
    assert account.selected_student_id is None


def test_process_guardian_agent_message_uses_channel_guardian_actor(db: Session, monkeypatch) -> None:
    guardian = _user(db, "guardian_agent", role="teacher")
    student = _user(db, "guardian_agent_student")
    access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-agent@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        selected_student_id=student.id,
    )
    db.add(account)
    db.flush()
    context = WechatGuardianStudentContext(account_id=account.id, student_id=student.id, push_time="20:30")
    db.add(context)
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    captured = {}

    async def fake_run_agent_turn(*_args, **kwargs):
        captured.update(kwargs)
        return "孩子最近在巩固函数。"

    sent = []
    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext)
    monkeypatch.setattr(inbound.agent, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(
        inbound,
        "send_ilink_text",
        lambda bot, user, text: sent.append((bot, user, text)) or "success",
    )

    asyncio.run(inbound.process_guardian_agent_message(account.id, student.id, "孩子最近怎么样"))

    assert captured["business_actor"] == "channel_guardian"
    assert sent == [
        (
            "shared-bot@im.bot",
            "guardian-agent@im.wechat",
            "孩子最近在巩固函数。",
        )
    ]


def test_guardian_duration_question_sends_short_today_summary_without_agent(db: Session, monkeypatch) -> None:
    guardian = _user(db, "guardian_today_summary", role="teacher")
    student = _user(db, "guardian_today_summary_student")
    access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-today-summary@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        selected_student_id=student.id,
    )
    db.add(account)
    db.flush()
    db.add(WechatGuardianStudentContext(account_id=account.id, student_id=student.id, push_time="20:30"))
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    async def fail_agent(*_args, **_kwargs):
        raise AssertionError("今日学习摘要不应调用 Agent")

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext)
    monkeypatch.setattr(inbound.agent, "run_agent_turn", fail_agent)
    monkeypatch.setattr(
        inbound.guardian_today,
        "build_guardian_today_learning_summary",
        lambda *_args, **_kwargs: "今天学习 30 分钟。\n\n完成：\n- 数学：一次函数错题复盘",
    )
    monkeypatch.setattr(
        inbound,
        "send_ilink_text",
        lambda bot, user, text: sent.append((bot, user, text)) or "success",
    )

    asyncio.run(inbound.process_guardian_agent_message(account.id, student.id, "我小孩今天学习了多久啊？"))

    assert sent == [
        (
            "shared-bot@im.bot",
            "guardian-today-summary@im.wechat",
            "今天学习 30 分钟。\n\n完成：\n- 数学：一次函数错题复盘",
        )
    ]


@pytest.mark.parametrize("question", ["今天学了多久", "今天学得怎么样"])
def test_guardian_today_query_runs_real_summary_from_db_not_mocked(db: Session, monkeypatch, question) -> None:
    """集成测试：家长问'今天学了多久'时，走真实 DB 查询 + 真实摘要函数，
    只 mock send_ilink_text 避免真实发消息。验证路由命中、绑定校验、真实输出链路。

    回归：旧测试把 build_guardian_today_learning_summary 也 mock 掉了，
    只验证 if 分支走向，没验证真实 DB 查询+真实摘要生成+发送的端到端链路。
    """
    guardian = _user(db, "guardian_integration_real", role="teacher")
    student = _user(db, "guardian_integration_student")
    access_service.bind_teacher_student(db, guardian.id, student.id)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian-integration-real@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        selected_student_id=student.id,
    )
    db.add(account)
    db.flush()
    db.add(WechatGuardianStudentContext(account_id=account.id, student_id=student.id, push_time="20:30"))
    # 造一条今天的真实时长反馈（数据库 DATETIME 按 UTC-naive 存储）
    db.add(
        LearningFeedback(
            student_id=student.id,
            feedback_type="duration",
            content="英语背单词学习了25分钟",
            created_at=datetime.utcnow().replace(microsecond=0),
        )
    )
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    async def fail_agent(*_args, **_kwargs):
        raise AssertionError("今日学习摘要不应调用 Agent")

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext)
    monkeypatch.setattr(inbound.agent, "run_agent_turn", fail_agent)
    # 不 mock build_guardian_today_learning_summary，用真实实现
    monkeypatch.setattr(
        inbound,
        "send_ilink_text",
        lambda bot, user, text: sent.append((bot, user, text)) or "success",
    )

    asyncio.run(inbound.process_guardian_agent_message(account.id, student.id, question))

    assert len(sent) == 1
    reply_text = sent[0][2]
    # 真实摘要应包含学生上报的真实时长，而非 mock 文案
    assert "今天学习 25 分钟" in reply_text
    # 不应调用 Agent（fail_agent 会在误调用时抛错）


@pytest.mark.parametrize(
    "content",
    ["今天学了什么", "今天学习了什么", "今天学习的内容", "今日做了什么", "今天学得怎么样"],
)
def test_guardian_today_content_questions_use_short_summary_intent(content: str) -> None:
    assert wechat_guardian._is_guardian_today_learning_query(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "明天要学多久",
        "考试要准备多久",
        "还要多久才能学完",
        "这个单词多久能背完",
        "他平时每天学习多久",
        "背完这本书需要多长时间",
    ],
)
def test_guardian_non_today_duration_question_stays_in_read_only_agent(content: str) -> None:
    """不含今天/今日语义的'多久'类问题应回归 Agent，不能误判为今日摘要。

    回归：旧实现只要命中'多久/多长时间/学习时长'就 return True，
    导致'明天要学多久''考试要准备多久'被答成今天学习时长，答非所问。
    """
    assert wechat_guardian._is_guardian_today_learning_query(content) is False


@pytest.mark.parametrize(
    "content",
    ["今天学了多久", "今日学习了多长时间", "孩子今天学习时长是多少", "今天学习多久了"],
)
def test_guardian_today_duration_question_uses_short_summary_intent(content: str) -> None:
    """含今天/今日语义的'多久'类问题应走今日短摘要。"""
    assert wechat_guardian._is_guardian_today_learning_query(content) is True


def test_guardian_non_today_question_stays_in_read_only_agent() -> None:
    assert wechat_guardian._is_guardian_today_learning_query("这周学习了多久") is False


def test_student_agent_messages_serialize_per_account_and_parallelize_across_accounts(db: Session, monkeypatch) -> None:
    accounts = [
        WechatAccount(
            user_id=2,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
            openid=f"agent-concurrency-{index}@im.wechat",
            status="active",
            bound_at=datetime.utcnow(),
        )
        for index in range(2)
    ]
    db.add_all(accounts)
    db.commit()

    class _SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    active = 0
    max_active = 0

    async def track_agent(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "处理完成"

    monkeypatch.setattr(inbound, "SessionLocal", _SessionContext)
    monkeypatch.setattr(inbound, "get_or_create_chat_session", lambda *_args: object())
    monkeypatch.setattr(inbound.agent, "run_agent_turn", track_agent)
    monkeypatch.setattr(inbound, "send_ilink_text", lambda *_args: "success")

    async def scenario() -> tuple[int, int]:
        nonlocal active, max_active
        await asyncio.gather(
            inbound.process_student_agent_message(accounts[0].id, "第一条"),
            inbound.process_student_agent_message(accounts[0].id, "第二条"),
        )
        same_account_max = max_active
        active = 0
        max_active = 0
        await asyncio.gather(
            inbound.process_student_agent_message(accounts[0].id, "A"),
            inbound.process_student_agent_message(accounts[1].id, "B"),
        )
        return same_account_max, max_active

    same_account_max, different_accounts_max = asyncio.run(scenario())

    assert same_account_max == 1
    assert different_accounts_max == 2


def test_create_bind_session_uses_configured_qr_and_expiry(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accounts.settings, "WECHAT_BIND_EXPIRE_SECONDS", 180)
    monkeypatch.setattr(
        accounts.settings,
        "WECHAT_OFFICIAL_ACCOUNT_QR_URL",
        "https://example.test/wechat-official-account.png",
    )
    user = _user(db, "wechat_session_student")
    started_at = datetime.utcnow()

    session = accounts.create_bind_session(db, user)

    assert session.user_id == user.id
    assert session.status == "pending"
    assert session.bind_code.startswith("W")
    assert len(session.bind_code) == 7
    assert session.scene.startswith("studybuddy_bind_")
    assert session.qr_value == "https://example.test/wechat-official-account.png"
    assert timedelta(seconds=179) <= session.expires_at - started_at <= timedelta(seconds=181)


def test_complete_bind_by_code_marks_session_bound_and_creates_account(db: Session) -> None:
    user = _user(db, "wechat_bind_student")
    session = accounts.create_bind_session(db, user)

    bound = accounts.complete_bind_by_code(db, session.bind_code, "openid-001")

    account = accounts.get_active_account(db, user.id)
    assert bound.status == "bound"
    assert bound.wechat_openid == "openid-001"
    assert bound.bound_at is not None
    assert account is not None
    assert account.user_id == user.id
    assert account.openid == "openid-001"
    assert account.status == "active"


def test_complete_bind_rejects_expired_code(db: Session) -> None:
    user = _user(db, "wechat_expired_student")
    session = accounts.create_bind_session(db, user)
    session.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    with pytest.raises(ValueError, match="绑定码已过期"):
        accounts.complete_bind_by_code(db, session.bind_code, "openid-expired")


def test_complete_bind_rejects_reused_code(db: Session) -> None:
    user = _user(db, "wechat_reused_student")
    session = accounts.create_bind_session(db, user)
    accounts.complete_bind_by_code(db, session.bind_code, "openid-reused")

    with pytest.raises(ValueError, match="绑定码已使用"):
        accounts.complete_bind_by_code(db, session.bind_code, "openid-reused-2")


def test_parent_invitation_rechecks_exact_student_relation(db: Session) -> None:
    parent = db.get(User, 1)
    student = db.get(User, 2)
    assert parent is not None
    assert student is not None
    session = accounts.create_bind_session(
        db,
        parent,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/parent-qr",
        provider_session_id="provider-parent-recheck",
        invited_by_user_id=student.id,
    )
    session.provider_account_id = "shared-bot@im.bot"
    session.wechat_openid = "parent-recheck@im.wechat"
    db.query(TeacherStudent).filter(
        TeacherStudent.teacher_id == parent.id,
        TeacherStudent.student_id == student.id,
    ).delete()
    db.commit()

    with pytest.raises(ValueError, match="家长账号尚未绑定该学生"):
        accounts.complete_bind_by_code(
            db,
            session.bind_code,
            "parent-recheck@im.wechat",
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
        )


def test_guardian_invitation_creates_channel_parent_without_web_registration(
    db: Session,
) -> None:
    student = db.get(User, 2)
    session = accounts.create_guardian_invitation(
        db,
        student,
        qr_value="https://example.test/new-guardian-qr",
        provider_session_id="new-guardian-provider-session",
    )
    assert session.user_id is None
    assert session.purpose == "guardian_invite"
    assert session.invited_by_user_id == student.id
    session.provider_account_id = "shared-bot@im.bot"
    session.wechat_openid = "new-guardian@im.wechat"
    db.commit()

    accounts.complete_bind_by_code(
        db,
        session.bind_code,
        "new-guardian@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
    )

    db.refresh(session)
    guardian = db.get(User, session.user_id)
    account = accounts.get_active_account_by_openid(
        db,
        "new-guardian@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
    )
    relation = db.get(TeacherStudent, (guardian.id, student.id))

    assert guardian.role == "teacher"
    assert guardian.web_login_enabled is False
    assert account is not None and account.user_id == guardian.id
    assert relation is not None
    assert session.status == "bound"


def test_guardian_invitation_reuses_same_guardian_for_second_student(db: Session) -> None:
    first_student = db.get(User, 2)
    second_student = _user(db, "guardian_second_student")
    first = accounts.create_guardian_invitation(
        db,
        first_student,
        qr_value="https://example.test/guardian-first-child",
        provider_session_id="guardian-first-child",
    )
    first.provider_account_id = "shared-bot@im.bot"
    first.wechat_openid = "guardian-two-children@im.wechat"
    db.commit()
    accounts.complete_bind_by_code(
        db,
        first.bind_code,
        first.wechat_openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=first.provider_account_id,
    )

    second = accounts.create_guardian_invitation(
        db,
        second_student,
        qr_value="https://example.test/guardian-second-child",
        provider_session_id="guardian-second-child",
    )
    second.provider_account_id = first.provider_account_id
    second.wechat_openid = first.wechat_openid
    db.commit()
    accounts.complete_bind_by_code(
        db,
        second.bind_code,
        second.wechat_openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=second.provider_account_id,
    )

    assert second.user_id == first.user_id
    assert db.get(TeacherStudent, (first.user_id, first_student.id)) is not None
    assert db.get(TeacherStudent, (first.user_id, second_student.id)) is not None
    assert (
        db.query(WechatAccount)
        .filter(
            WechatAccount.channel == WECHAT_CHANNEL_ILINK_BOT,
            WechatAccount.provider_account_id == first.provider_account_id,
            WechatAccount.openid == first.wechat_openid,
            WechatAccount.status == "active",
        )
        .count()
        == 1
    )


def test_guardian_invitation_allows_second_guardian_for_same_student(db: Session) -> None:
    student = db.get(User, 2)
    guardian_ids: list[int] = []
    for suffix in ("first", "second"):
        session = accounts.create_guardian_invitation(
            db,
            student,
            qr_value=f"https://example.test/{suffix}-guardian",
            provider_session_id=f"{suffix}-guardian",
        )
        session.provider_account_id = "shared-bot@im.bot"
        session.wechat_openid = f"{suffix}-guardian@im.wechat"
        db.commit()
        accounts.complete_bind_by_code(
            db,
            session.bind_code,
            session.wechat_openid,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=session.provider_account_id,
        )
        guardian_ids.append(session.user_id)

    assert len(set(guardian_ids)) == 2
    assert all(db.get(TeacherStudent, (guardian_id, student.id)) for guardian_id in guardian_ids)


def test_guardian_invitation_rejects_wechat_identity_owned_by_student(db: Session) -> None:
    student = db.get(User, 2)
    db.add(
        WechatAccount(
            user_id=student.id,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
            openid="student-cannot-be-guardian@im.wechat",
            active_identity_key=accounts.build_active_identity_key(
                WECHAT_CHANNEL_ILINK_BOT,
                "shared-bot@im.bot",
                "student-cannot-be-guardian@im.wechat",
            ),
            status="active",
            bound_at=datetime.utcnow(),
        )
    )
    db.commit()
    session = accounts.create_guardian_invitation(
        db,
        student,
        qr_value="https://example.test/student-role-conflict",
        provider_session_id="student-role-conflict",
    )
    session.provider_account_id = "shared-bot@im.bot"
    session.wechat_openid = "student-cannot-be-guardian@im.wechat"
    db.commit()

    with pytest.raises(ValueError, match="学生微信身份不能绑定为家长"):
        accounts.complete_bind_by_code(
            db,
            session.bind_code,
            session.wechat_openid,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id=session.provider_account_id,
        )


def test_complete_bind_rejects_openid_already_bound_to_other_user(db: Session) -> None:
    user_a = _user(db, "wechat_openid_a")
    user_b = _user(db, "wechat_openid_b")
    session_a = accounts.create_bind_session(db, user_a)
    session_b = accounts.create_bind_session(db, user_b)
    accounts.complete_bind_by_code(db, session_a.bind_code, "openid-same")

    with pytest.raises(ValueError, match="微信已绑定其他账号"):
        accounts.complete_bind_by_code(db, session_b.bind_code, "openid-same")


def test_bind_race_unique_conflict_is_rejected(db: Session, monkeypatch) -> None:
    user = _user(db, "wechat_bind_race")
    session = accounts.create_bind_session(db, user)

    def raise_unique_conflict() -> None:
        raise IntegrityError("insert", {}, RuntimeError("duplicate active identity"))

    monkeypatch.setattr(db, "commit", raise_unique_conflict)

    with pytest.raises(ValueError, match="微信已绑定其他账号"):
        accounts.complete_bind_by_code(db, session.bind_code, "openid-race")


def test_active_identity_key_separates_channels_and_provider_accounts() -> None:
    official = accounts.build_active_identity_key(WECHAT_CHANNEL_OFFICIAL_ACCOUNT, None, "same-user")
    first_bot = accounts.build_active_identity_key(WECHAT_CHANNEL_ILINK_BOT, "bot-1", "same-user")
    second_bot = accounts.build_active_identity_key(WECHAT_CHANNEL_ILINK_BOT, "bot-2", "same-user")

    assert len({official, first_bot, second_bot}) == 3
    assert all(len(value) == 64 for value in (official, first_bot, second_bot))


def test_channel_bindings_and_unbind_are_isolated(db: Session) -> None:
    official_user = _user(db, "wechat_channel_official")
    bot_user = _user(db, "wechat_channel_bot")
    official_session = accounts.create_bind_session(db, official_user)
    bot_session = accounts.create_bind_session(
        db,
        bot_user,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-qr",
        provider_session_id="provider-session-1",
    )
    bot_session.provider_account_id = "bot-account-1"
    bot_session.wechat_openid = "same-channel-user"
    db.commit()

    accounts.complete_bind_by_code(db, official_session.bind_code, "same-channel-user")
    accounts.complete_bind_by_code(
        db,
        bot_session.bind_code,
        "same-channel-user",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="bot-account-1",
    )
    accounts.unbind_account(db, bot_user, channel=WECHAT_CHANNEL_ILINK_BOT)

    official_account = accounts.get_active_account(db, official_user.id, channel=WECHAT_CHANNEL_OFFICIAL_ACCOUNT)
    assert official_account is not None
    assert official_account.channel == WECHAT_CHANNEL_OFFICIAL_ACCOUNT
    assert accounts.get_active_account(db, bot_user.id, channel=WECHAT_CHANNEL_ILINK_BOT) is None
    assert bot_session.provider_session_id == "provider-session-1"
    assert bot_session.provider_account_id == "bot-account-1"


def test_ilink_bind_rejects_provider_account_mismatch(db: Session) -> None:
    user = _user(db, "wechat_ilink_provider_mismatch")
    session = accounts.create_bind_session(
        db,
        user,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-qr",
        provider_session_id="provider-session-mismatch",
    )
    session.provider_account_id = "shared-bot@im.bot"
    session.wechat_openid = "scanner@im.wechat"
    db.commit()

    with pytest.raises(ValueError, match="微信学习助手身份不一致"):
        accounts.complete_bind_by_code(
            db,
            session.bind_code,
            "scanner@im.wechat",
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="other-bot@im.bot",
        )


def test_ilink_bind_rejects_scanner_user_mismatch(db: Session) -> None:
    user = _user(db, "wechat_ilink_scanner_mismatch")
    session = accounts.create_bind_session(
        db,
        user,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-qr",
        provider_session_id="provider-session-scanner",
    )
    session.provider_account_id = "shared-bot@im.bot"
    session.wechat_openid = "scanner@im.wechat"
    db.commit()

    with pytest.raises(ValueError, match="扫码微信身份不一致"):
        accounts.complete_bind_by_code(
            db,
            session.bind_code,
            "other-user@im.wechat",
            channel=WECHAT_CHANNEL_ILINK_BOT,
            provider_account_id="shared-bot@im.bot",
        )


def test_ilink_bind_refreshes_provider_identity_when_not_yet_synced(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """扫码后立即发码（前端轮询还没刷新 provider_account_id）时，
    complete_bind 应自己调 Bot 微服务刷新扫码身份后绑定成功，而非直接判身份不一致。"""
    user = _user(db, "wechat_ilink_race_refresh")
    session = accounts.create_bind_session(
        db,
        user,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        qr_value="https://example.test/ilink-qr-race",
        provider_session_id="provider-session-race",
    )
    # 模拟前端轮询尚未刷新：provider_account_id 仍为 None
    assert session.provider_account_id is None

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "status": "confirmed",
                "provider_account_id": "bot-account-race",
                "ilink_user_id": "scanner-race@im.wechat",
                "qr_value": "https://example.test/ilink-qr-race",
            }

    monkeypatch.setattr(accounts.httpx, "get", lambda *_a, **_k: _Resp())

    bound = accounts.complete_bind_by_code(
        db,
        session.bind_code,
        "scanner-race@im.wechat",
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="bot-account-race",
    )
    assert bound.status == "bound"
    assert bound.provider_account_id == "bot-account-race"


def test_unbind_account_marks_active_account_unbound(db: Session) -> None:
    user = _user(db, "wechat_unbind_student")
    session = accounts.create_bind_session(db, user)
    accounts.complete_bind_by_code(db, session.bind_code, "openid-unbind")

    accounts.unbind_account(db, user)

    assert accounts.get_active_account(db, user.id) is None


def test_unbind_account_invalidates_all_active_openids(db: Session) -> None:
    user = _user(db, "wechat_unbind_all_student")
    first_session = accounts.create_bind_session(db, user)
    accounts.complete_bind_by_code(db, first_session.bind_code, "openid-unbind-first")
    second_session = accounts.create_bind_session(db, user)
    accounts.complete_bind_by_code(db, second_session.bind_code, "openid-unbind-second")

    accounts.unbind_account(db, user)

    active_count = db.query(WechatAccount).filter(WechatAccount.user_id == user.id, WechatAccount.status == "active").count()
    assert active_count == 0


def test_dispatch_parent_reminder_sends_once_at_configured_time(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        openid="openid-parent-reminder",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime.utcnow(),
        reminder_times=["09:00"],
    )
    db.add(account)
    db.commit()
    sent: list[str] = []

    first = dispatch.dispatch_parent_reminders(db, now=now, send_text=lambda _openid, content: sent.append(content))
    second = dispatch.dispatch_parent_reminders(db, now=now, send_text=lambda _openid, content: sent.append(content))

    assert first == {"sent": 1, "paused": 0, "failed": 0}
    assert second == {"sent": 0, "paused": 0, "failed": 0}
    assert len(sent) == 1
    assert "测试学生今日学情" in sent[0]


def test_dispatch_parent_reminder_claim_blocks_competing_dispatcher(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        openid="openid-parent-claim",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime.utcnow(),
        reminder_times=["09:00"],
    )
    db.add(account)
    db.commit()
    sent: list[str] = []
    competing_results: list[dict[str, int]] = []

    def _send(_openid: str, content: str) -> None:
        sent.append(content)
        competing_results.append(
            dispatch.dispatch_parent_reminders(
                db,
                now=now,
                send_text=lambda _nested_openid, nested_content: sent.append(nested_content),
            )
        )

    result = dispatch.dispatch_parent_reminders(db, now=now, send_text=_send)

    assert result == {"sent": 1, "paused": 0, "failed": 0}
    assert competing_results == [{"sent": 0, "paused": 0, "failed": 0}]
    assert len(sent) == 1


def test_dispatch_parent_reminder_pauses_outside_interaction_window(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        openid="openid-parent-paused",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 7, 0, 0),
        reminder_times=["09:00"],
    )
    db.add(account)
    db.commit()

    result = dispatch.dispatch_parent_reminders(db, now=now, send_text=lambda _openid, _content: None)

    assert result == {"sent": 0, "paused": 1, "failed": 0}


def test_dispatch_parent_reminder_does_not_mark_provider_failure_as_sent(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        openid="openid-parent-failed",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime.utcnow(),
        reminder_times=["09:00"],
    )
    db.add(account)
    db.commit()

    def _fail(_openid: str, _content: str) -> None:
        raise RuntimeError("provider unavailable")

    result = dispatch.dispatch_parent_reminders(db, now=now, send_text=_fail)

    db.refresh(account)
    assert result == {"sent": 0, "paused": 0, "failed": 1}
    assert account.last_reminder_sent_at is None


def test_ilink_parent_reminder_increments_quota_only_after_success(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-reminder-success@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 10, 0, 50),
        reminder_times=["09:00"],
    )
    account.proactive_message_count = 0
    db.add(account)
    db.commit()
    sent: list[tuple[str, str, str]] = []

    result = dispatch.dispatch_parent_reminders(
        db,
        now=now,
        send_ilink=lambda bot_id, user_id, content: (sent.append((bot_id, user_id, content)) or "success"),
    )
    repeated = dispatch.dispatch_parent_reminders(
        db,
        now=now,
        send_ilink=lambda bot_id, user_id, content: (sent.append((bot_id, user_id, content)) or "success"),
    )

    db.refresh(account)
    assert result == {"sent": 1, "paused": 0, "failed": 0}
    assert repeated == {"sent": 0, "paused": 0, "failed": 0}
    assert len(sent) == 1
    assert sent[0][0:2] == ("shared-bot@im.bot", "parent-reminder-success@im.wechat")
    assert "测试学生今日学情" in sent[0][2]
    assert account.proactive_message_count == 1
    assert account.last_reminder_sent_at is not None


def test_ilink_parent_reminder_pauses_at_proactive_quota(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-reminder-quota@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 10, 0, 50),
        reminder_times=["09:00"],
    )
    account.proactive_message_count = dispatch.settings.WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT
    db.add(account)
    db.commit()

    def fail_if_called(*_args):
        raise AssertionError("quota exhausted account must not call provider")

    result = dispatch.dispatch_parent_reminders(db, now=now, send_ilink=fail_if_called)

    assert result == {"sent": 0, "paused": 1, "failed": 0}


@pytest.mark.parametrize("provider_status", ["window_closed", "session_expired", "not_allowed"])
def test_ilink_parent_reminder_pauses_for_provider_session_status(db: Session, provider_status: str) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid=f"parent-reminder-{provider_status}@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 10, 0, 50),
        reminder_times=["09:00"],
    )
    account.proactive_message_count = 0
    db.add(account)
    db.commit()

    result = dispatch.dispatch_parent_reminders(
        db,
        now=now,
        send_ilink=lambda *_args: provider_status,
    )

    db.refresh(account)
    assert result == {"sent": 0, "paused": 1, "failed": 0}
    assert account.proactive_message_count == 0
    assert account.last_reminder_sent_at is None


def test_ilink_parent_reminder_keeps_failure_out_of_success_counters(db: Session) -> None:
    now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-reminder-failed@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
        last_interacted_at=datetime(2026, 7, 10, 0, 50),
        reminder_times=["09:00"],
    )
    account.proactive_message_count = 0
    db.add(account)
    db.commit()

    result = dispatch.dispatch_parent_reminders(
        db,
        now=now,
        send_ilink=lambda *_args: "failed",
    )

    db.refresh(account)
    assert result == {"sent": 0, "paused": 0, "failed": 1}
    assert account.proactive_message_count == 0
    assert account.last_reminder_sent_at is None


def test_ilink_interaction_resets_proactive_quota(db: Session) -> None:
    account = WechatAccount(
        user_id=1,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="parent-interaction-reset@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    account.proactive_message_count = 2
    db.add(account)
    db.commit()

    interacted = accounts.record_interaction(
        db,
        account.openid,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id=account.provider_account_id,
    )

    assert interacted is account
    assert account.proactive_message_count == 0
    assert account.proactive_message_window_started_at is not None


def test_send_customer_text_uses_configured_wechat_provider(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def _get(url, params, timeout):
        calls["get"] = (url, params, timeout)
        return _Response({"access_token": "provider-token"})

    def _post(url, params, json, timeout):
        calls["post"] = (url, params, json, timeout)
        return _Response({"errcode": 0})

    monkeypatch.setattr(messaging.httpx, "get", _get)
    monkeypatch.setattr(messaging.httpx, "post", _post)

    messaging.send_customer_text("openid-provider", "今日学情摘要")

    assert calls["get"] == (
        messaging.settings.WECHAT_ACCESS_TOKEN_URL,
        {
            "grant_type": "client_credential",
            "appid": messaging.settings.WECHAT_APP_ID,
            "secret": reveal_secret(messaging.settings.WECHAT_APP_SECRET),
        },
        messaging.settings.WECHAT_API_TIMEOUT_SECONDS,
    )
    assert calls["post"] == (
        messaging.settings.WECHAT_CUSTOMER_MESSAGE_URL,
        {"access_token": "provider-token"},
        {"touser": "openid-provider", "msgtype": "text", "text": {"content": "今日学情摘要"}},
        messaging.settings.WECHAT_API_TIMEOUT_SECONDS,
    )


def test_send_ilink_text_uses_shared_bot_message_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "window_closed"}

    def _post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Response()

    monkeypatch.setattr(messaging.httpx, "post", _post)

    status = messaging.send_ilink_text("shared-bot@im.bot", "parent-contract@im.wechat", "今日学情摘要")

    assert status == "window_closed"
    assert captured == {
        "url": f"{messaging.settings.WECHAT_BOT_SERVICE_URL}/v1/messages",
        "headers": {"X-Internal-Token": reveal_secret(messaging.settings.WECHAT_BOT_INTERNAL_TOKEN)},
        "json": {
            "provider_account_id": "shared-bot@im.bot",
            "ilink_user_id": "parent-contract@im.wechat",
            "content": "今日学情摘要",
        },
        "timeout": messaging.settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
    }
