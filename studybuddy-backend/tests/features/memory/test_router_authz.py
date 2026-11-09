"""记忆模块路由的越权校验：家长/老师只能访问已绑定的学生。

conftest 固定造了 teacher=1 绑定 student=2（TeacherStudent(1, 2)）。
"""


def _token(client, username: str, password: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_parent_can_search_bound_student(client):
    token = _token(client, "teacher", "teacher123")
    r = client.get("/api/memory/search", params={"student_id": 2}, headers=_auth(token))
    assert r.status_code == 200, r.text


def test_parent_cannot_search_unbound_student(client):
    token = _token(client, "teacher", "teacher123")
    r = client.get("/api/memory/search", params={"student_id": 999999}, headers=_auth(token))
    assert r.status_code == 403, r.text


def test_parent_must_pass_student_id(client):
    token = _token(client, "teacher", "teacher123")
    r = client.get("/api/memory/search", headers=_auth(token))
    assert r.status_code == 400, r.text


def test_parent_cannot_list_relations_of_unbound_student(client):
    token = _token(client, "teacher", "teacher123")
    r = client.get("/api/memory/relations", params={"student_id": 999999}, headers=_auth(token))
    assert r.status_code == 403, r.text


def test_parent_cannot_create_relations_for_unbound_student(client):
    token = _token(client, "teacher", "teacher123")
    r = client.post(
        "/api/memory/relations",
        params={"student_id": 999999},
        json=[{"source_type": "note", "source_id": 1, "target_type": "error_book", "target_id": 1, "relation": "related_to"}],
        headers=_auth(token),
    )
    assert r.status_code == 403, r.text


def test_student_cannot_read_other_student(client):
    token = _token(client, "student", "student123")
    r = client.get("/api/memory/search", params={"student_id": 999999}, headers=_auth(token))
    assert r.status_code == 403, r.text
