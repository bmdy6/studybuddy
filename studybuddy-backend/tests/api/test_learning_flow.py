from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.features.learning.schemas.learning_flow import LearningFlowEntry
from app.utils.security import hash_password


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_student(db: Session, *, bound: bool) -> tuple[User, str]:
    password = "student123"
    student = User(
        username=f"flow_{uuid4().hex[:12]}",
        password_hash=hash_password(password),
        role="student",
        display_name="入口权限测试学生",
    )
    db.add(student)
    db.flush()
    if bound:
        db.add(TeacherStudent(teacher_id=1, student_id=student.id))
    db.commit()
    db.refresh(student)
    return student, password


def _empty_entry() -> LearningFlowEntry:
    return LearningFlowEntry(
        kind="empty",
        title="今天想先学什么",
        description="告诉助手一道不会的题、一个知识点，或者今天的计划。",
        primary_label="开始学习",
        prompt="",
        source_type=None,
        source_id=None,
        evidence=[],
    )


def test_student_can_only_read_own_entry(client: TestClient, db: Session, monkeypatch):
    student, password = _create_student(db, bound=False)
    seen: list[int] = []
    monkeypatch.setattr(
        "app.features.learning.router_learning_flow.get_learning_flow_entry",
        lambda _db, student_id: seen.append(student_id) or _empty_entry(),
    )
    token = _login(client, student.username, password)

    own = client.get("/api/learning-flow/entry", headers=_headers(token))
    blocked = client.get("/api/learning-flow/entry?student_id=2", headers=_headers(token))

    assert own.status_code == 200, own.text
    assert seen == [student.id]
    assert blocked.status_code == 403


def test_bound_teacher_can_read_entry(client: TestClient, db: Session, monkeypatch):
    student, _ = _create_student(db, bound=True)
    monkeypatch.setattr("app.features.learning.router_learning_flow.get_learning_flow_entry", lambda _db, _student_id: _empty_entry())
    token = _login(client, "teacher", "teacher123")

    response = client.get(f"/api/learning-flow/entry?student_id={student.id}", headers=_headers(token))

    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "empty"


def test_teacher_cannot_read_unbound_entry(client: TestClient, db: Session, monkeypatch):
    student, _ = _create_student(db, bound=False)
    monkeypatch.setattr("app.features.learning.router_learning_flow.get_learning_flow_entry", lambda _db, _student_id: _empty_entry())
    token = _login(client, "teacher", "teacher123")

    response = client.get(f"/api/learning-flow/entry?student_id={student.id}", headers=_headers(token))

    assert response.status_code == 403


def test_review_entry_requires_exactly_one_source(client: TestClient):
    token = _login(client, "student", "student123")

    missing = client.get("/api/learning-flow/review-entry", headers=_headers(token))
    duplicated = client.get(
        "/api/learning-flow/review-entry?error_id=1&knowledge_tag=函数",
        headers=_headers(token),
    )

    assert missing.status_code == 422
    assert duplicated.status_code == 422


def test_unbound_teacher_cannot_build_review_entry(client: TestClient, db: Session):
    student, _ = _create_student(db, bound=False)
    token = _login(client, "teacher", "teacher123")

    response = client.get(
        f"/api/learning-flow/review-entry?student_id={student.id}&knowledge_tag=函数",
        headers=_headers(token),
    )

    assert response.status_code == 403
