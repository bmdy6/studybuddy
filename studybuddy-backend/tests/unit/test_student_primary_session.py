"""学生长期主会话单测（PR-05）。

覆盖：
- 新学生第一次进入创建主会话，并写入 primary_student_id。
- 老学生存在多个旧会话时按 updated_at desc, id desc 认领一条，不合并不删除不迁移。
- 学生重复请求创建新会话不得产生多个主会话。
- 真实并发：两个线程同时为同一新学生创建主会话，DB 唯一约束保证只剩一个主会话。
- 学生/辅导者权限：辅导者不应触发学生主会话逻辑；学生请求才走主会话。
- 认领规则确定性：多会话时主会话稳定指向最新活跃一条。
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chat import ChatSession
from app.models.user import User
from app.features.chat import sessions
from app.utils.security import hash_password


def _make_student(db: Session, username: str = "primary-student") -> User:
    """创建一个独立学生（独立 username，避免和 fixture 固定账号冲突）。"""
    student = User(
        username=username,
        password_hash=hash_password("x"),
        role="student",
        display_name=username,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _make_student_session(
    db: Session,
    student: User,
    *,
    title: str = "旧会话",
    role_at_create: str = "student",
    primary: bool = False,
) -> ChatSession:
    """直接构造一条 ChatSession，绕过 create_session 的业务校验。"""
    session = ChatSession(
        user_id=student.id,
        student_id=student.id,
        role_at_create=role_at_create,
        title=title,
        primary_student_id=student.id if primary else None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_new_student_creates_primary_session_with_marker(db: Session) -> None:
    """新学生第一次进入：没有会话 -> 创建主会话并写入 primary_student_id。"""
    student = _make_student(db, "primary-new")

    session = sessions.get_or_create_student_primary_session(db, student)

    assert session is not None
    assert session.student_id == student.id
    assert session.user_id == student.id
    assert session.role_at_create == "student"
    assert session.primary_student_id == student.id
    # 库里只应该有一个主会话
    primary_count = (
        db.query(ChatSession)
        .filter(
            ChatSession.student_id == student.id,
            ChatSession.primary_student_id.isnot(None),
        )
        .count()
    )
    assert primary_count == 1


def test_repeat_entry_returns_same_primary_session(db: Session) -> None:
    """学生重复请求创建主会话：返回同一个会话，不产生多个。"""
    student = _make_student(db, "primary-repeat")
    first = sessions.get_or_create_student_primary_session(db, student)
    second = sessions.get_or_create_student_primary_session(db, student)
    third = sessions.get_or_create_student_primary_session(db, student)

    assert first.id == second.id == third.id
    primary_count = (
        db.query(ChatSession)
        .filter(ChatSession.primary_student_id == student.id)
        .count()
    )
    assert primary_count == 1


def test_old_student_multiple_sessions_claims_latest_by_updated_at_then_id(db: Session) -> None:
    """老学生已有多个旧会话：按 updated_at desc, id desc 认领最新一条作为主会话。

    不合并消息、不删除旧会话、不迁移聊天内容：旧会话数量不变，仅一条被标记 primary。
    """
    student = _make_student(db, "primary-old")
    old_a = _make_student_session(db, student, title="旧会话A")
    old_b = _make_student_session(db, student, title="旧会话B")
    old_c = _make_student_session(db, student, title="旧会话C")

    # 模拟 updated_at 不同：old_b 最早被更新（旧），old_a 最新更新（活）。
    # ChatSession.updated_at 由 onupdate 维护；这里通过显式赋值构造确定性顺序。
    from datetime import datetime, timedelta

    base = datetime(2026, 7, 1, 12, 0, 0)
    old_a.updated_at = base + timedelta(hours=2)  # 最新活跃
    old_b.updated_at = base  # 最早
    old_c.updated_at = base + timedelta(hours=1)
    db.commit()

    primary = sessions.get_or_create_student_primary_session(db, student)

    # updated_at 最大的是 old_a
    assert primary.id == old_a.id
    assert primary.primary_student_id == student.id

    # 旧会话数量不变（3 条全部保留，只有一条被认领为主会话）
    all_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.student_id == student.id)
        .order_by(ChatSession.id)
        .all()
    )
    assert {s.id for s in all_sessions} == {old_a.id, old_b.id, old_c.id}
    primary_marked = [s for s in all_sessions if s.primary_student_id is not None]
    assert len(primary_marked) == 1
    assert primary_marked[0].id == old_a.id


def test_old_student_tiebreak_by_id_desc_when_updated_at_equal(db: Session) -> None:
    """updated_at 相同时按 id desc 取最新一条，规则确定性。"""
    student = _make_student(db, "primary-tiebreak")
    first = _make_student_session(db, student, title="先建")
    second = _make_student_session(db, student, title="后建")
    # 强制 updated_at 完全一致
    same_ts = first.updated_at
    second.updated_at = same_ts
    first.updated_at = same_ts
    db.commit()

    primary = sessions.get_or_create_student_primary_session(db, student)
    assert primary.id == second.id  # id 更大者胜出


def test_concurrent_create_does_not_produce_duplicate_primary() -> None:
    """真实并发：两个线程同时为新学生创建主会话。

    必须依赖 DB 唯一约束：冲突方回滚后重新读取已存在主会话，最终只有一个主会话。
    不使用 db fixture（savepoint 隔离），用真实 SessionLocal 独立连接触发真实 IntegrityError。
    """
    # 先用一个独立 session 准备一个干净的新学生，并提交到真实库
    setup = SessionLocal()
    try:
        # 清理可能残留的同名学生（防御性）
        existing = setup.query(User).filter(User.username == "primary-concurrent").first()
        if existing:
            setup.query(ChatSession).filter(
                ChatSession.student_id == existing.id
            ).delete(synchronize_session=False)
            setup.delete(existing)
            setup.commit()
        student = User(
            username="primary-concurrent",
            password_hash=hash_password("x"),
            role="student",
            display_name="primary-concurrent",
        )
        setup.add(student)
        setup.commit()
        setup.refresh(student)
        student_id = student.id
    finally:
        setup.close()

    def call() -> int:
        s = SessionLocal()
        try:
            u = s.get(User, student_id)
            session = sessions.get_or_create_student_primary_session(s, u)
            return session.id
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(call) for _ in range(2)]
        results = [f.result() for f in futures]

    # 两个线程必须拿到同一个主会话 id
    assert results[0] == results[1], f"并发创建产生了不同主会话: {results}"

    # 库里该学生只能有一个 primary_student_id 标记的主会话
    verify = SessionLocal()
    try:
        primary_count = (
            verify.query(ChatSession)
            .filter(ChatSession.primary_student_id == student_id)
            .count()
        )
        assert primary_count == 1, f"并发后主会话数量异常: {primary_count}"
    finally:
        # 清理真实库本次产生数据
        verify.query(ChatSession).filter(
            ChatSession.student_id == student_id
        ).delete(synchronize_session=False)
        verify.query(User).filter(User.id == student_id).delete(synchronize_session=False)
        verify.commit()
        verify.close()


def test_teacher_session_does_not_get_primary_marker(db: Session) -> None:
    """辅导者创建的会话不应被标记为学生主会话。

    辅导者保留原有多会话能力：辅导者会话 primary_student_id 必须保持 NULL。
    get_or_create_student_primary_session 是学生专属，不应被辅导者调用认领。
    """
    from app.models.teacher_student import TeacherStudent

    teacher = User(
        username="primary-teacher",
        password_hash=hash_password("x"),
        role="teacher",
        display_name="primary-teacher",
    )
    student = User(
        username="primary-teacher-student",
        password_hash=hash_password("x"),
        role="student",
        display_name="primary-teacher-student",
    )
    db.add_all([teacher, student])
    db.commit()
    db.refresh(teacher)
    db.refresh(student)
    db.add(TeacherStudent(teacher_id=teacher.id, student_id=student.id))
    db.commit()

    # 辅导者按原流程创建会话：不应写入 primary_student_id
    teacher_session = sessions.create_session(db, teacher, student.id)
    assert teacher_session.primary_student_id is None
    assert teacher_session.user_id == teacher.id
    assert teacher_session.student_id == student.id

    # 学生随后进入认领主会话：应认领学生自己的会话，而不是辅导者建的会话
    # （辅导者会话 user_id 是辅导者，不在学生自己会话范围内）
    primary = sessions.get_or_create_student_primary_session(db, student)
    assert primary.user_id == student.id
    assert primary.primary_student_id == student.id
    # 辅导者会话依旧未被标记
    db.refresh(teacher_session)
    assert teacher_session.primary_student_id is None


def test_student_role_only_can_claim_own_primary(db: Session) -> None:
    """学生只能操作自己的主会话；服务层用 user.id 而非外部 student_id。"""
    student = _make_student(db, "primary-own")

    session = sessions.get_or_create_student_primary_session(db, student)

    # primary_student_id 必须等于学生自己 id，不接受任何外部 student_id
    assert session.primary_student_id == student.id
    assert session.student_id == student.id
    assert session.user_id == student.id


def test_existing_primary_session_not_reassigned(db: Session) -> None:
    """已有主会话时，新增旧会话不应改变主会话归属。"""
    student = _make_student(db, "primary-stable")
    primary_first = sessions.get_or_create_student_primary_session(db, student)

    # 模拟之后又冒出来一条非主会话（如旧数据回流或并发补建）
    _make_student_session(db, student, title="后出现的旧会话")

    primary_again = sessions.get_or_create_student_primary_session(db, student)
    assert primary_again.id == primary_first.id
