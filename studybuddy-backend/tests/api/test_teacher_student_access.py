"""家长-学生绑定权限集成测试。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.utils.security import hash_password


def _teacher_token(client: TestClient) -> str:
    """登录老师账号并返回 access token。"""
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    """生成认证请求头。"""
    return {"Authorization": f"Bearer {token}"}


def _create_unbound_student(db: Session) -> User:
    """创建一个未绑定给老师的测试学生。"""
    student = User(
        username=f"unbound_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name="未绑定学生",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_teacher_cannot_open_chat_for_unbound_student(client: TestClient, db: Session):
    """老师不能为未绑定学生创建对话会话。"""
    token = _teacher_token(client)
    student = _create_unbound_student(db)

    r = client.post("/api/chat/sessions", json={"student_id": student.id}, headers=_headers(token))

    assert r.status_code == 403


def test_teacher_cannot_read_unbound_student_notes(client: TestClient, db: Session):
    """老师不能查看未绑定学生的笔记列表。"""
    token = _teacher_token(client)
    student = _create_unbound_student(db)

    r = client.get(f"/api/notes?student_id={student.id}", headers=_headers(token))

    assert r.status_code == 403


def test_teacher_cannot_read_unbound_student_diagnosis(client: TestClient, db: Session):
    """老师不能查看未绑定学生的学情诊断。"""
    token = _teacher_token(client)
    student = _create_unbound_student(db)

    r = client.get(f"/api/diagnosis/{student.id}", headers=_headers(token))

    assert r.status_code == 403


def test_teacher_cannot_read_unbound_student_profile_tools(client: TestClient, db: Session):
    """老师不能访问未绑定学生的 P2 画像类接口。"""
    token = _teacher_token(client)
    student = _create_unbound_student(db)

    interests = client.get(f"/api/students/{student.id}/interests", headers=_headers(token))
    attributes = client.get(f"/api/students/{student.id}/attributes", headers=_headers(token))

    assert interests.status_code == 403
    assert attributes.status_code == 403
