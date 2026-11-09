"""试卷导入与查询 API 集成测试。

覆盖：
- 有效导入 → 201 + question_count
- score<=0 → 422（字段级错误）
- 缺少 grading → 422
- 未登录 → 401
- 学生导入 → 403
- 查询详情不含 answer_json（★ 安全红线）
- 列表查询
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.user import User


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


VALID_EXAM = {
    "schema_version": 1,
    "title": "U5 测验",
    "subject": "english",
    "feedback_mode": "after_submit",
    "shuffle_groups": False,
    "questions": [
        {
            "type": "single_choice",
            "stem": "He ___ to school.",
            "options": ["go", "goes", "went", "gone"],
            "answer": "went",
            "score": 2,
            "knowledge_tags": ["过去时"],
            "group_id": "grammar",
            "grading": {"rule_type": "auto_exact", "matcher": "exact", "match_params": {}},
        },
        {
            "type": "translation",
            "stem": "翻译：我去学校。",
            "answer": "I went to school.",
            "score": 5,
            "knowledge_tags": ["翻译"],
            "grading": {"rule_type": "manual"},
        },
    ],
}


def test_import_valid_exam(client: TestClient):
    token = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_headers(token))
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["question_count"] == 2
    assert data["exam_id"] > 0


def test_import_invalid_score(client: TestClient):
    token = _teacher_token(client)
    bad = {**VALID_EXAM, "questions": [{**VALID_EXAM["questions"][0], "score": -1}]}
    r = client.post("/api/exam/import", json=bad, headers=_headers(token))
    assert r.status_code == 422
    assert "score" in str(r.json())


def test_import_missing_grading(client: TestClient):
    token = _teacher_token(client)
    q = {**VALID_EXAM["questions"][0]}
    del q["grading"]
    bad = {**VALID_EXAM, "questions": [q]}
    r = client.post("/api/exam/import", json=bad, headers=_headers(token))
    assert r.status_code == 422
    assert "grading" in str(r.json())


def test_import_unauthorized(client: TestClient):
    r = client.post("/api/exam/import", json=VALID_EXAM)
    assert r.status_code == 401 or r.status_code == 403


def test_import_student_forbidden(client: TestClient):
    token = _student_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_headers(token))
    assert r.status_code == 403


def test_get_exam_detail_no_answer_json(client: TestClient):
    """★ 安全红线：详情响应绝不包含 answer_json。"""
    token = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_headers(token))
    exam_id = r.json()["exam_id"]

    r = client.get(f"/api/exam/{exam_id}", headers=_headers(token))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["id"] == exam_id
    assert len(detail["questions"]) == 2
    for q in detail["questions"]:
        assert "answer_json" not in q
        assert "answer" not in q


def test_list_exams(client: TestClient):
    token = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_headers(token))
    exam_id = r.json()["exam_id"]

    r = client.get("/api/exam", headers=_headers(token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert any(item["id"] == exam_id for item in items)
    item = next(i for i in items if i["id"] == exam_id)
    assert item["title"] == "U5 测验"
    assert item["question_count"] == 2
    assert item["total_score"] == 7  # 2 + 5
    assert "answer" not in item


def test_student_only_sees_assigned_published_exams(client: TestClient, db):
    """学生列表只返回已分发的 published，草稿和未分发试卷不暴露。"""
    teacher_token = _teacher_token(client)
    draft = client.post("/api/exam/import", json={**VALID_EXAM, "title": "草稿卷"}, headers=_headers(teacher_token)).json()["exam_id"]
    published = client.post("/api/exam/import", json={**VALID_EXAM, "title": "发布卷"}, headers=_headers(teacher_token)).json()["exam_id"]

    r = client.patch(f"/api/exam/{published}/status", json={"status": "published"}, headers=_headers(teacher_token))
    assert r.status_code == 200, r.text
    student = db.query(User).filter(User.username == "student").first()
    assert student is not None
    assigned = client.post(
        f"/api/exam/{published}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    assert assigned.status_code == 201, assigned.text

    student_token = _student_token(client)
    r = client.get("/api/exam", headers=_headers(student_token))
    assert r.status_code == 200, r.text
    ids = {item["id"] for item in r.json()}
    assert published in ids
    assert draft not in ids

    hidden_detail = client.get(f"/api/exam/{draft}", headers=_headers(student_token))
    assert hidden_detail.status_code == 403
