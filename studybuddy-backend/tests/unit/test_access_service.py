from datetime import datetime

from app.models.user import User
from app.models.wechat import (
    WECHAT_CHANNEL_ILINK_BOT,
    WechatAccount,
    WechatGuardianStudentContext,
)
from app.core.auth import access_service


def test_resolve_business_actor_distinguishes_coach_and_channel_guardian() -> None:
    teacher = User(
        id=10,
        username="internal-teacher",
        password_hash="unused",
        role="teacher",
        web_login_enabled=True,
    )
    guardian_account = WechatAccount(
        id=20,
        user_id=teacher.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="guardian@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )

    assert access_service.resolve_business_actor(teacher) == "coach"
    assert access_service.resolve_business_actor(teacher, guardian_account) == "channel_guardian"


def test_resolve_business_actor_keeps_student_identity() -> None:
    student = User(
        id=11,
        username="student-actor",
        password_hash="unused",
        role="student",
        web_login_enabled=True,
    )

    assert access_service.resolve_business_actor(student) == "student"


def test_guardian_student_contexts_are_independent_per_student(db) -> None:
    guardian = db.get(User, 1)
    account = WechatAccount(
        user_id=guardian.id,
        channel=WECHAT_CHANNEL_ILINK_BOT,
        provider_account_id="shared-bot@im.bot",
        openid="multi-child-guardian@im.wechat",
        status="active",
        bound_at=datetime.utcnow(),
    )
    second_student = User(
        username="second-student",
        password_hash="unused",
        role="student",
        web_login_enabled=True,
    )
    db.add_all([account, second_student])
    db.flush()

    first = WechatGuardianStudentContext(
        account_id=account.id,
        student_id=2,
        push_time="20:00",
    )
    second = WechatGuardianStudentContext(
        account_id=account.id,
        student_id=second_student.id,
        push_time="21:00",
    )
    db.add_all([first, second])
    db.commit()

    assert first.id != second.id
    assert first.push_time == "20:00"
    assert second.push_time == "21:00"
