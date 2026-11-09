"""答题提交与判分编排集成测试。

端到端流程：老师导入试卷 → 学生 start → 学生 submit → 老师查 pending → 老师人工批改。
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.answer import Answer
from app.models.exam_record import ExamRecord

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


def _teacher_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _student_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assign_exam_to_student(client: TestClient, exam_id: int, teacher_token: str, student_id: int = 2) -> None:
    r = client.post(
        f"/api/exam/{exam_id}/assignments",
        json={"student_ids": [student_id]},
        headers=_h(teacher_token),
    )
    assert r.status_code == 201, r.text


def _setup_exam_and_record(client: TestClient) -> tuple[int, list[int], int]:
    """导入、发布、分发试卷 + 学生 start，返回 (exam_id, question_ids, exam_record_id)。"""
    tt = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_h(tt))
    exam_id = r.json()["exam_id"]
    publish = client.patch(f"/api/exam/{exam_id}/status", json={"status": "published"}, headers=_h(tt))
    assert publish.status_code == 200, publish.text
    _assign_exam_to_student(client, exam_id, tt)

    detail = client.get(f"/api/exam/{exam_id}", headers=_h(tt)).json()
    question_ids = [q["id"] for q in detail["questions"]]

    st = _student_token(client)
    r = client.post(f"/api/exam/{exam_id}/start", headers=_h(st))
    assert r.status_code == 201, r.text
    record_id = r.json()["exam_record_id"]
    return exam_id, question_ids, record_id


def test_start_exam_reuses_latest_in_progress_record(client: TestClient):
    """重复进入进行中的试卷时复用记录，避免一次点击产生多条作答。"""
    exam_id, _, record_id = _setup_exam_and_record(client)
    st = _student_token(client)

    repeated = client.post(f"/api/exam/{exam_id}/start", headers=_h(st))

    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["exam_record_id"] == record_id


def test_submit_exam(client: TestClient):
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    st = _student_token(client)

    r = client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [
                {"question_id": question_ids[0], "student_answer": "went"},
                {"question_id": question_ids[1], "student_answer": "I went to school yesterday."},
            ],
        },
        headers=_h(st),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "submitted"
    assert data["pending_manual_count"] == 1  # 第 2 题是 manual
    assert data["objective_score"] == 2  # 第 1 题 auto_exact 答对 2 分


def test_submit_wrong_answer(client: TestClient):
    """答错客观题 → objective_score=0，结果明细可用于记录错因。"""
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    st = _student_token(client)

    r = client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [
                {"question_id": question_ids[0], "student_answer": "goed"},  # 错答
            ],
        },
        headers=_h(st),
    )
    assert r.status_code == 200, r.text
    assert r.json()["objective_score"] == 0

    result = client.get(f"/api/exam-record/{record_id}/result", headers=_h(st))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["exam_record_id"] == record_id
    assert data["exam_id"] == exam_id
    assert data["feedback_mode"] == "after_submit"
    assert data["answers"][0]["question_id"] == question_ids[0]
    assert data["answers"][0]["student_answer"] == "goed"
    assert data["answers"][0]["correct_answer"] == "went"
    assert data["answers"][0]["is_correct"] is False
    assert data["answers"][0]["knowledge_tags"] == ["过去时"]


def test_submit_not_owner(client: TestClient):
    """teacher 角色不能走学生提交接口 → 403。"""
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    tt = _teacher_token(client)

    r = client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [{"question_id": question_ids[0], "student_answer": "went"}],
        },
        headers=_h(tt),
    )
    assert r.status_code == 403  # require_student 拦截


def test_start_draft_exam_rejected(client: TestClient):
    """草稿试卷不能被学生开始作答。"""
    tt = _teacher_token(client)
    r = client.post("/api/exam/import", json=VALID_EXAM, headers=_h(tt))
    exam_id = r.json()["exam_id"]
    st = _student_token(client)

    r = client.post(f"/api/exam/{exam_id}/start", headers=_h(st))

    assert r.status_code == 404
    assert "未发布" in r.json()["detail"]


def test_cleanup_stale_empty_exam_records(client: TestClient, db):
    """只清理过期且无作答的 in_progress 空考试记录。"""
    exam_id, question_ids, _ = _setup_exam_and_record(client)
    old_time = datetime.utcnow() - timedelta(days=3)

    stale_empty = ExamRecord(exam_id=exam_id, student_id=2, status="in_progress", started_at=old_time)
    fresh_empty = ExamRecord(exam_id=exam_id, student_id=2, status="in_progress", started_at=datetime.utcnow())
    stale_with_answer = ExamRecord(exam_id=exam_id, student_id=2, status="in_progress", started_at=old_time)
    db.add_all([stale_empty, fresh_empty, stale_with_answer])
    db.commit()
    db.refresh(stale_empty)
    db.refresh(fresh_empty)
    db.refresh(stale_with_answer)

    db.add(
        Answer(
            exam_record_id=stale_with_answer.id,
            question_id=question_ids[0],
            student_answer="go",
            score=Decimal("0"),
            is_correct=0,
            is_manual_graded=0,
        )
    )
    db.commit()

    tt = _teacher_token(client)
    r = client.delete("/api/exam-records/stale?older_than_hours=24", headers=_h(tt))

    assert r.status_code == 200, r.text
    data = r.json()
    assert stale_empty.id in data["deleted_record_ids"]
    assert fresh_empty.id not in data["deleted_record_ids"]
    assert stale_with_answer.id not in data["deleted_record_ids"]
    assert db.get(ExamRecord, stale_empty.id) is None
    assert db.get(ExamRecord, fresh_empty.id) is not None
    assert db.get(ExamRecord, stale_with_answer.id) is not None


def test_student_cannot_cleanup_stale_exam_records(client: TestClient):
    st = _student_token(client)

    r = client.delete("/api/exam-records/stale", headers=_h(st))

    assert r.status_code == 403


def test_submit_rejects_question_from_other_exam(client: TestClient):
    """不能把别的试卷题目提交到当前考试记录。"""
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    other_exam_id, other_question_ids, _ = _setup_exam_and_record(client)
    assert other_exam_id != exam_id
    st = _student_token(client)

    r = client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [{"question_id": other_question_ids[0], "student_answer": "went"}],
        },
        headers=_h(st),
    )

    assert r.status_code == 400
    assert "不属于当前试卷" in r.json()["detail"]


def test_submit_rejects_wrong_exam_record_route(client: TestClient):
    """路由 exam_id 必须与 exam_record.exam_id 一致。"""
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    other_exam_id, _, _ = _setup_exam_and_record(client)
    assert other_exam_id != exam_id
    st = _student_token(client)

    r = client.post(
        f"/api/exam/{other_exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [{"question_id": question_ids[0], "student_answer": "went"}],
        },
        headers=_h(st),
    )

    assert r.status_code == 400
    assert "考试记录不属于该试卷" in r.json()["detail"]


def test_pending_and_grade(client: TestClient):
    exam_id, question_ids, record_id = _setup_exam_and_record(client)
    st = _student_token(client)
    # 先提交（含 1 道 manual 待批改）
    client.post(
        f"/api/exam/{exam_id}/submit",
        json={
            "exam_record_id": record_id,
            "answers": [
                {"question_id": question_ids[0], "student_answer": "went"},
                {"question_id": question_ids[1], "student_answer": "I went to school."},
            ],
        },
        headers=_h(st),
    )

    tt = _teacher_token(client)
    r = client.get("/api/answers/pending", headers=_h(tt))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    # 找到本次提交的那条 manual 题（question_ids[1]），跨测试数据隔离
    my_item = next(
        (i for i in items if i["question_id"] == question_ids[1]),
        None,
    )
    assert my_item is not None, "本次提交的 manual 题未出现在 pending"
    assert my_item["reference_answer"] == "I went to school."
    assert my_item["student_answer"] == "I went to school."

    answer_id = my_item["answer_id"]
    r = client.post(
        f"/api/answer/{answer_id}/grade",
        json={"manual_score": 4.5, "manual_comment": "时态正确，拼写小错"},
        headers=_h(tt),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["graded"] is True
    assert float(data["score"]) == 4.5
    assert data["is_correct"] is True  # 4.5/5 = 0.9 >= 0.6

    # 批改后这条不再出现在 pending
    r = client.get("/api/answers/pending", headers=_h(tt))
    still_pending = [i for i in r.json() if i["answer_id"] == answer_id]
    assert len(still_pending) == 0
