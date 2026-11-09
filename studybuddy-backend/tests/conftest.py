"""pytest 全局配置：测试数据隔离。

每个测试用独立事务，测试结束自动回滚，不污染开发库。
关键：覆盖 app.database.get_db，让 FastAPI 端点测试也走事务回滚的 session。

实现：用 SQLAlchemy 的 SAVEPOINT（嵌套事务）——外层事务回滚时，
测试中的所有 commit 会被内嵌事务包住，最终一起回滚。
"""

from collections.abc import Generator
import os
import sys

import pytest

# Never inherit a developer's application database or model credentials.
# Set these explicitly for the disposable MySQL instance before invoking pytest.
if (
    os.environ.get("STUDYBUDDY_TEST_DATABASE") != "1"
    or not os.environ.get("DB_NAME", "").endswith("_test")
    or os.environ.get("DB_HOST") not in {"127.0.0.1", "localhost"}
):
    raise pytest.UsageError("Tests require STUDYBUDDY_TEST_DATABASE=1, a local DB_HOST and DB_NAME ending in _test.")
if "--run-live" not in sys.argv:
    os.environ["LLM_API_KEY"] = ""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.utils.security import hash_password


def pytest_addoption(parser):
    """--run-live：允许跑标记为 live 的真实 LLM/视觉测试（默认 skip，耗 token 需网络）。"""
    parser.addoption("--run-live", action="store_true", default=False, help="跑 live 标记的真实 LLM 测试")


def pytest_collection_modifyitems(config, items):
    """未传 --run-live 时，跳过所有 live 标记的测试。"""
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="需 --run-live 才跑（真实 LLM 调用，耗 token）")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def _seed_fixed_test_users(session: Session) -> None:
    """为旧单测提供稳定的 teacher=1 / student=2 基线。

    这些数据写在测试事务里，测试结束会跟随外层 transaction rollback，
    不会污染开发库真实账号，也不依赖开发库当前自增 id。
    """
    for user in session.query(User).filter(User.username.in_(["teacher", "student"]), User.id.notin_([1, 2])).all():
        user.username = f"fixture-shadow-{user.id}-{user.username}"

    teacher = session.get(User, 1)
    if teacher is None:
        teacher = User(id=1, username="teacher", password_hash=hash_password("teacher123"), role="teacher", display_name="测试家长")
        session.add(teacher)
    else:
        teacher.username = "teacher"
        teacher.password_hash = hash_password("teacher123")
        teacher.role = "teacher"
        teacher.display_name = "测试家长"

    student = session.get(User, 2)
    if student is None:
        student = User(id=2, username="student", password_hash=hash_password("student123"), role="student", display_name="测试学生")
        session.add(student)
    else:
        student.username = "student"
        student.password_hash = hash_password("student123")
        student.role = "student"
        student.display_name = "测试学生"

    # SessionLocal disables autoflush; insert both parents before the FK link.
    session.flush()
    if session.get(TeacherStudent, (1, 2)) is None:
        session.add(TeacherStudent(teacher_id=1, student_id=2))
    session.flush()


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """每个测试函数用独立事务，结束回滚，不污染开发库。

    用嵌套事务（SAVEPOINT）：测试里的 db.commit() 只提交到 savepoint，
    外层 rollback 时全部撤销。
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        _seed_fixed_test_users(session)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """TestClient 注入事务隔离的 db，覆盖 get_db 依赖。"""

    def _override_get_db():
        try:
            yield db
        finally:
            pass  # 事务由 db fixture 统一回滚

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def real_client() -> Generator[TestClient, None, None]:
    """不走事务隔离的 TestClient（用真实库）。

    仅供需要异步 task 读到测试数据的场景用（如 SSE：agent_loop 在 to_thread 里
    用独立连接，看不到未提交的事务数据）。测试后按 id 精确清理本次新建的会话。

    为什么不靠标题清理：发首条消息后 maybe_auto_title 会把标题改成消息内容
    （如 "hi"、"查诊断"），原先按 title=="test" 删会漏删，导致开发库残留。
    改为跑前快照 session id 集合，跑后删 diff 出来的新增 id（消息 CASCADE 删）。
    """
    from app.database import SessionLocal
    from app.models.chat import ChatSession

    snapshot = SessionLocal()
    pre_ids = set()
    try:
        # SSE uses independent connections, so its synthetic login baseline must
        # be committed in the dedicated test database, not inside a savepoint.
        _seed_fixed_test_users(snapshot)
        snapshot.commit()
        pre_ids = {row[0] for row in snapshot.query(ChatSession.id).all()}
    finally:
        snapshot.close()

    with TestClient(app) as c:
        yield c

    cleanup = SessionLocal()
    try:
        new_ids = [row[0] for row in cleanup.query(ChatSession.id).all() if row[0] not in pre_ids]
        if new_ids:
            cleanup.query(ChatSession).filter(ChatSession.id.in_(new_ids)).delete(synchronize_session=False)
            cleanup.commit()
    finally:
        cleanup.close()
