from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.utils.security import hash_password


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_unbound_student(db: Session) -> User:
    student = User(
        username=f"supervision_unbound_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name="未绑定学生",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_bound_teacher_can_read_supervision_summary(client: TestClient):
    token = _login(client, "teacher", "teacher123")

    response = client.get("/api/students/2/supervision-summary", headers=_headers(token))

    assert response.status_code == 200, response.text
    assert response.json()["student_id"] == 2


def test_teacher_cannot_read_unbound_supervision_summary(client: TestClient, db: Session):
    student = _create_unbound_student(db)
    token = _login(client, "teacher", "teacher123")

    response = client.get(f"/api/students/{student.id}/supervision-summary", headers=_headers(token))

    assert response.status_code == 403


def test_student_cannot_read_parent_supervision_summary(client: TestClient):
    token = _login(client, "student", "student123")

    response = client.get("/api/students/2/supervision-summary", headers=_headers(token))

    assert response.status_code == 403
