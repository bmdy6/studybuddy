"""认证接口集成测试。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.auth import access_service
from app.utils.security import hash_password, verify_password


def _create_student(db: Session, display_name: str) -> User:
    """创建一个事务内可回滚的测试学生。"""
    student = User(
        username=f"student_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name=display_name,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_teacher_login_returns_real_student_children(client: TestClient, db: Session):
    """老师登录时返回数据库中的学生列表。"""
    student = _create_student(db, "登录测试学生")
    access_service.bind_teacher_student(db, 1, student.id)

    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})

    assert r.status_code == 200, r.text
    children = r.json()["children"]
    assert any(c["id"] == student.id and c["display_name"] == "登录测试学生" for c in children)


def test_teacher_login_excludes_unbound_students(client: TestClient, db: Session):
    """老师登录时不返回未绑定的学生。"""
    student = _create_student(db, "未绑定学生")

    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})

    assert r.status_code == 200, r.text
    children = r.json()["children"]
    assert not any(c["id"] == student.id for c in children)


def test_student_login_returns_empty_children(client: TestClient):
    """学生登录时 children 固定为空数组。"""
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})

    assert r.status_code == 200, r.text
    assert r.json()["children"] == []


def test_login_token_is_persistent_for_family_usage(client: TestClient):
    """网页登录态应足够持久，避免学生每天反复输入账号密码。"""
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})

    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] >= 30 * 24 * 3600


def test_channel_guardian_cannot_login_to_web(client: TestClient, db: Session):
    """渠道家长只作为内部权限主体，不能登录辅导者工作台。"""
    guardian = User(
        username=f"guardian_{uuid4().hex[:12]}",
        password_hash=hash_password("not-for-login"),
        role="teacher",
        display_name="微信家长",
        web_login_enabled=False,
    )
    db.add(guardian)
    db.commit()

    response = client.post(
        "/auth/login",
        json={"username": guardian.username, "password": "not-for-login"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"


def test_register_creates_student_and_returns_persistent_login(client: TestClient, db: Session):
    """新用户注册后直接获得学生登录态。"""
    username = f"new_student_{uuid4().hex[:12]}"

    response = client.post("/auth/register", json={"username": f"  {username}  ", "password": "student123"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "student"
    assert body["display_name"] == username
    assert body["expires_in"] >= 30 * 24 * 3600
    assert body["children"] == []

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["username"] == username


def test_register_hashes_password(client: TestClient, db: Session):
    """注册密码只保存 hash，不落明文。"""
    username = f"hashed_student_{uuid4().hex[:12]}"

    response = client.post("/auth/register", json={"username": username, "password": "student123"})

    assert response.status_code == 201, response.text
    user = db.query(User).filter(User.username == username).one()
    assert user.password_hash != "student123"
    assert verify_password("student123", user.password_hash)


def test_register_rejects_duplicate_username(client: TestClient, db: Session):
    """同一用户名不能创建第二个账号。"""
    username = f"duplicate_student_{uuid4().hex[:12]}"
    payload = {"username": username, "password": "student123"}

    first = client.post("/auth/register", json=payload)
    second = client.post("/auth/register", json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "用户名已被使用"
    assert db.query(User).filter(User.username == username).count() == 1


def test_register_rejects_blank_username(client: TestClient):
    """只包含空白的用户名不能注册。"""
    response = client.post("/auth/register", json={"username": "   ", "password": "student123"})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "用户名不能为空"


def test_register_rejects_short_password(client: TestClient):
    """密码长度继续遵循现有最小六位约束。"""
    response = client.post("/auth/register", json={"username": "new_student", "password": "12345"})

    assert response.status_code == 422, response.text


# ---------- 模式切换（study/hobby）----------

def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_profile_returns_default_mode(client: TestClient):
    """新用户默认 mode=study（学习模式）。"""
    token = _student_token(client)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "study"


def test_switch_mode_to_hobby_and_back(client: TestClient):
    """同账号可在 study/hobby 间切换，PATCH /auth/me 持久化。"""
    token = _student_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.patch("/auth/me", json={"mode": "hobby"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hobby"

    r = client.patch("/auth/me", json={"mode": "study"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "study"


def test_switch_mode_rejects_invalid(client: TestClient):
    """非法 mode 值被拒绝（fail-closed）。"""
    token = _student_token(client)
    r = client.patch("/auth/me", json={"mode": "music"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422
