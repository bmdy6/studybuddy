"""学生主会话路由集成测试（PR-05）。

覆盖：
- GET /api/chat/sessions/primary 学生身份返回主会话（201 创建语义改成 200 返回）。
- 重复请求返回同一个会话。
- 辅导者调用主会话端点应被拒绝（辅导者保留多会话能力，不参与学生主会话）。
- 未登录拒绝。
- 会话返回结构复用 SessionItem。
"""

import pytest
from fastapi.testclient import TestClient

from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.utils.security import hash_password


def _student_token(client: TestClient, username: str, password: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_student_primary_session_creates_then_returns_same(db, client) -> None:
    """学生第一次调用创建主会话，第二次返回同一个。"""
    # 准备一个独立学生并登录
    student = User(
        username="primary-router-student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="primary-router-student",
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    token = _student_token(client, "primary-router-student", "student123")

    r1 = client.get("/api/chat/sessions/primary", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["student_id"] == student.id
    assert body1["user_id"] == student.id

    r2 = client.get("/api/chat/sessions/primary", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["id"] == body1["id"]

    # 库里只能有一条主会话
    primary_count = (
        db.query(ChatSession)
        .filter(ChatSession.primary_student_id == student.id)
        .count()
    )
    assert primary_count == 1


def test_student_legacy_create_endpoint_reuses_primary_session(db, client) -> None:
    """旧 POST 创建入口也必须收敛到同一个学生主会话。"""
    student = User(
        username="primary-legacy-create",
        password_hash=hash_password("student123"),
        role="student",
        display_name="primary-legacy-create",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    token = _student_token(client, student.username, "student123")
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/chat/sessions",
        headers=headers,
        json={"student_id": student.id},
    )
    second = client.post(
        "/api/chat/sessions",
        headers=headers,
        json={"student_id": student.id},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    sessions = db.query(ChatSession).filter(ChatSession.user_id == student.id).all()
    assert len(sessions) == 1
    assert sessions[0].primary_student_id == student.id


def test_student_can_start_new_context_and_clear_messages(db, client) -> None:
    student = User(
        username="primary-context-reset",
        password_hash=hash_password("student123"),
        role="student",
        display_name="primary-context-reset",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    token = _student_token(client, student.username, "student123")
    headers = {"Authorization": f"Bearer {token}"}

    primary = client.get("/api/chat/sessions/primary", headers=headers).json()
    session = db.get(ChatSession, primary["id"])
    session.context_summary = "旧的滚动摘要"
    db.add(ChatMessage(session_id=session.id, role="user", content="旧话题"))
    db.add(ChatMessage(session_id=session.id, role="assistant", content="旧回复"))
    db.commit()
    response = client.post(
        f"/api/chat/sessions/{session.id}/context/reset",
        headers=headers,
    )

    assert response.status_code == 204, response.text
    db.refresh(session)
    assert session.context_summary is None
    assert session.context_summary_message_id is None
    history = client.get(f"/api/chat/sessions/{session.id}/messages", headers=headers)
    assert [item["content"] for item in history.json()] == []


def test_student_can_reset_task_session_context(db, client) -> None:
    student = User(
        username="task-context-reset",
        password_hash=hash_password("student123"),
        role="student",
        display_name="task-context-reset",
    )
    db.add(student)
    db.flush()
    task_session = ChatSession(
        user_id=student.id,
        student_id=student.id,
        role_at_create="student",
        title="学习任务",
        session_type="task",
        plan_item_id=987654,
    )
    db.add(task_session)
    db.commit()
    token = _student_token(client, student.username, "student123")

    headers = {"Authorization": f"Bearer {token}"}
    sessions = client.get("/api/chat/sessions", headers=headers)
    listed_task = next(item for item in sessions.json() if item["id"] == task_session.id)
    assert listed_task["session_type"] == "task"
    assert listed_task["plan_item_id"] == task_session.plan_item_id

    response = client.post(
        f"/api/chat/sessions/{task_session.id}/context/reset",
        headers=headers,
    )

    assert response.status_code == 204


def test_student_primary_session_rejects_teacher(client) -> None:
    """辅导者调用学生主会话端点应被拒绝（403），保留辅导者多会话能力。"""
    token = _teacher_token(client)
    r = client.get("/api/chat/sessions/primary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


def test_student_primary_session_requires_auth(client) -> None:
    """未登录拒绝。"""
    r = client.get("/api/chat/sessions/primary")
    assert r.status_code in (401, 403)
