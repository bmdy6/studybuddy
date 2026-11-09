"""试卷定向分发权限 API 集成测试。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.exam_record import ExamRecord
from app.models.error_book import ErrorBook
from app.core.auth import access_service
from app.utils.security import hash_password


VALID_EXAM = {
    "schema_version": 1,
    "title": "定向分发试卷",
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
        }
    ],
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _get_user(db: Session, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return user


def _create_unbound_student(db: Session, display_name: str = "未绑定学生") -> User:
    student = User(
        username=f"unbound_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name=display_name,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _create_bound_student(db: Session, teacher_id: int, display_name: str = "绑定学生") -> User:
    student = _create_unbound_student(db, display_name=display_name)
    access_service.bind_teacher_student(db, teacher_id, student.id)
    return student


def _create_published_exam(client: TestClient, teacher_token: str, title: str = "定向试卷") -> int:
    payload = {**VALID_EXAM, "title": title}
    imported = client.post("/api/exam/import", headers=_headers(teacher_token), json=payload)
    assert imported.status_code in (200, 201), imported.text
    exam_id = imported.json()["exam_id"]
    published = client.patch(
        f"/api/exam/{exam_id}/status",
        headers=_headers(teacher_token),
        json={"status": "published"},
    )
    assert published.status_code == 200, published.text
    return exam_id


def _start_exam(client: TestClient, exam_id: int, student_token: str) -> int:
    resp = client.post(f"/api/exam/{exam_id}/start", headers=_headers(student_token))
    assert resp.status_code == 201, resp.text
    return resp.json()["exam_record_id"]


def test_teacher_assigns_exam_to_bound_student(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    student = _get_user(db, "student")
    exam_id = _create_published_exam(client, teacher_token)

    resp = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id], "due_at": "2026-07-10T20:00:00+08:00", "note": "周五前完成"},
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[0]["student_id"] == student.id
    assert data[0]["status"] == "assigned"
    assert data[0]["note"] == "周五前完成"


def test_teacher_assigns_exam_to_multiple_bound_students(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    teacher = _get_user(db, "teacher")
    student = _get_user(db, "student")
    extra_student = _create_bound_student(db, teacher.id, display_name="额外绑定学生")
    exam_id = _create_published_exam(client, teacher_token, title="批量分发试卷")

    resp = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id, extra_student.id], "note": "两位同学都要做"},
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert [item["student_id"] for item in data] == [student.id, extra_student.id]
    assert all(item["status"] == "assigned" for item in data)
    assert {item["student_name"] for item in data} == {student.display_name, "额外绑定学生"}


def test_teacher_cannot_assign_exam_to_unbound_student(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    unbound_student = _create_unbound_student(db)
    exam_id = _create_published_exam(client, teacher_token)

    resp = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [unbound_student.id]},
    )

    assert resp.status_code == 403
    assert "未绑定" in resp.json()["detail"]


def test_student_only_lists_assigned_exams(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    student_token = _login(client, "student", "student123")
    student = _get_user(db, "student")
    assigned_exam_id = _create_published_exam(client, teacher_token, title="定向卷")
    hidden_exam_id = _create_published_exam(client, teacher_token, title="未分发卷")
    assigned = client.post(
        f"/api/exam/{assigned_exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    assert assigned.status_code == 201, assigned.text

    resp = client.get("/api/exam", headers=_headers(student_token))

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert assigned_exam_id in ids
    assert hidden_exam_id not in ids


def test_exam_list_returns_assignment_metadata_for_student(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    student_token = _login(client, "student", "student123")
    student = _get_user(db, "student")

    assigned_exam_id = _create_published_exam(client, teacher_token, title="带分发信息试卷")
    assigned = client.post(
        f"/api/exam/{assigned_exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id], "due_at": "2026-07-10T20:00:00+08:00", "note": "周五前完成"},
    )
    assert assigned.status_code == 201, assigned.text

    resp = client.get("/api/exam", headers=_headers(student_token))

    assert resp.status_code == 200, resp.text
    data = {item["id"]: item for item in resp.json()}
    assert data[assigned_exam_id]["visibility"] == "assigned"
    assert data[assigned_exam_id]["assignment_status"] == "assigned"
    assert data[assigned_exam_id]["assignment_note"] == "周五前完成"
    assert data[assigned_exam_id]["assignment_due_at"].startswith("2026-07-10T20:00:00")


def test_student_cannot_start_exam_without_assignment(client: TestClient):
    teacher_token = _login(client, "teacher", "teacher123")
    student_token = _login(client, "student", "student123")
    exam_id = _create_published_exam(client, teacher_token, title="未分发不可开始")

    resp = client.post(f"/api/exam/{exam_id}/start", headers=_headers(student_token))

    assert resp.status_code == 403
    assert "未分发" in resp.json()["detail"]


def test_submit_exam_updates_assignment_status_to_submitted(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    student_token = _login(client, "student", "student123")
    student = _get_user(db, "student")
    exam_id = _create_published_exam(client, teacher_token, title="提交后更新状态")
    assigned = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    assert assigned.status_code == 201, assigned.text

    detail = client.get(f"/api/exam/{exam_id}", headers=_headers(student_token))
    assert detail.status_code == 200, detail.text
    question_id = detail.json()["questions"][0]["id"]
    record_id = _start_exam(client, exam_id, student_token)

    submitted = client.post(
        f"/api/exam/{exam_id}/submit",
        headers=_headers(student_token),
        json={
            "exam_record_id": record_id,
            "answers": [{"question_id": question_id, "student_answer": "went"}],
        },
    )
    assert submitted.status_code == 200, submitted.text

    assignments = client.get(f"/api/exam/{exam_id}/assignments", headers=_headers(teacher_token))
    assert assignments.status_code == 200, assignments.text
    data = assignments.json()
    assert data[0]["student_id"] == student.id
    assert data[0]["status"] == "submitted"


def test_teacher_can_list_exam_assignments(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    teacher = _get_user(db, "teacher")
    student = _get_user(db, "student")
    extra_student = _create_bound_student(db, teacher.id, display_name="第二个绑定学生")
    exam_id = _create_published_exam(client, teacher_token, title="查看分发列表")
    assigned = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id, extra_student.id], "note": "查看分发"},
    )
    assert assigned.status_code == 201, assigned.text

    resp = client.get(f"/api/exam/{exam_id}/assignments", headers=_headers(teacher_token))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [item["student_id"] for item in data] == [student.id, extra_student.id]
    assert [item["student_name"] for item in data] == [student.display_name, "第二个绑定学生"]
    assert all(item["note"] == "查看分发" for item in data)


def test_teacher_can_cancel_exam_assignment(client: TestClient, db: Session):
    teacher_token = _login(client, "teacher", "teacher123")
    student = _get_user(db, "student")
    student_token = _login(client, "student", "student123")
    exam_id = _create_published_exam(client, teacher_token, title="取消分发")
    assigned = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    assert assigned.status_code == 201, assigned.text
    assignment_id = assigned.json()[0]["id"]

    cancelled = client.delete(
        f"/api/exam/{exam_id}/assignments/{assignment_id}",
        headers=_headers(teacher_token),
    )

    assert cancelled.status_code == 204, cancelled.text
    listed = client.get(f"/api/exam/{exam_id}/assignments", headers=_headers(teacher_token))
    assert listed.status_code == 200, listed.text
    data = listed.json()
    assert len(data) == 1
    assert data[0]["id"] == assignment_id
    assert data[0]["status"] == "cancelled"

    denied = client.post(f"/api/exam/{exam_id}/start", headers=_headers(student_token))
    assert denied.status_code == 403, denied.text


def test_exam_list_returns_completion_status_for_student(client: TestClient, db: Session):
    """学生试卷列表返回完成状态（latest_record_status + latest_record_id）。"""
    teacher_token = _login(client, "teacher", "teacher123")
    student_token = _login(client, "student", "student123")
    student = _get_user(db, "student")
    exam_id = _create_published_exam(client, teacher_token, title="完成状态卷")
    assigned = client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    assert assigned.status_code == 201, assigned.text

    def item_for(eid: int) -> dict:
        resp = client.get("/api/exam", headers=_headers(student_token))
        assert resp.status_code == 200, resp.text
        return {i["id"]: i for i in resp.json()}[eid]

    # 未做
    item = item_for(exam_id)
    assert item["latest_record_status"] is None
    assert item["latest_record_id"] is None

    # 开始作答 -> in_progress
    record_id = _start_exam(client, exam_id, student_token)
    item = item_for(exam_id)
    assert item["latest_record_status"] == "in_progress"
    assert item["latest_record_id"] == record_id

    # 提交 -> submitted
    detail = client.get(f"/api/exam/{exam_id}", headers=_headers(student_token))
    question_id = detail.json()["questions"][0]["id"]
    submitted = client.post(
        f"/api/exam/{exam_id}/submit",
        headers=_headers(student_token),
        json={"exam_record_id": record_id, "answers": [{"question_id": question_id, "student_answer": "went"}]},
    )
    assert submitted.status_code == 200, submitted.text
    item = item_for(exam_id)
    assert item["latest_record_status"] == "submitted"
    assert item["latest_record_id"] == record_id


def _set_record_started_at(db: Session, record_id: int, seconds_ago: int) -> None:
    """把考试记录的 started_at 拨到 N 秒前，模拟真实用时。"""
    from datetime import datetime, timedelta, timezone

    record = db.get(ExamRecord, record_id)
    assert record is not None
    record.started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.commit()


def test_submit_valid_answer_writes_error_book(client: TestClient, db: Session):
    """正常作答（有效用时+非空答案）答错 → 错题照常进错题本。"""
    teacher_token = _login(client, "teacher", "teacher123")
    student = _get_user(db, "student")
    student_token = _login(client, "student", "student123")
    exam_id = _create_published_exam(client, teacher_token, title="门禁-正常作答")
    client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    detail = client.get(f"/api/exam/{exam_id}", headers=_headers(student_token)).json()
    question_id = detail["questions"][0]["id"]
    record_id = _start_exam(client, exam_id, student_token)
    _set_record_started_at(db, record_id, 60)  # 60 秒前开始，正常用时

    resp = client.post(
        f"/api/exam/{exam_id}/submit",
        headers=_headers(student_token),
        json={"exam_record_id": record_id, "answers": [{"question_id": question_id, "student_answer": "go"}]},
    )
    assert resp.status_code == 200, resp.text
    err = db.query(ErrorBook).filter(ErrorBook.student_id == student.id, ErrorBook.question_id == question_id).first()
    assert err is not None, "正常作答的错题应进错题本"
    record = db.get(ExamRecord, record_id)
    assert record.suspected_low_quality == 0


def test_submit_blank_answers_skips_error_book(client: TestClient, db: Session):
    """空白答案占比高（敷衍）→ 不写错题本，标记 suspected_low_quality。"""
    teacher_token = _login(client, "teacher", "teacher123")
    student = _get_user(db, "student")
    student_token = _login(client, "student", "student123")
    exam_id = _create_published_exam(client, teacher_token, title="门禁-空白作答")
    client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    detail = client.get(f"/api/exam/{exam_id}", headers=_headers(student_token)).json()
    question_id = detail["questions"][0]["id"]
    record_id = _start_exam(client, exam_id, student_token)
    _set_record_started_at(db, record_id, 60)

    resp = client.post(
        f"/api/exam/{exam_id}/submit",
        headers=_headers(student_token),
        json={"exam_record_id": record_id, "answers": [{"question_id": question_id, "student_answer": ""}]},
    )
    assert resp.status_code == 200, resp.text
    err = db.query(ErrorBook).filter(ErrorBook.student_id == student.id, ErrorBook.question_id == question_id).first()
    assert err is None, "空白答案不应进错题本"
    record = db.get(ExamRecord, record_id)
    assert record.suspected_low_quality == 1


def test_submit_too_fast_skips_error_book(client: TestClient, db: Session):
    """极速交卷（<15 秒/题）→ 不写错题本，标记 suspected_low_quality。"""
    teacher_token = _login(client, "teacher", "teacher123")
    student = _get_user(db, "student")
    student_token = _login(client, "student", "student123")
    exam_id = _create_published_exam(client, teacher_token, title="门禁-极速交卷")
    client.post(
        f"/api/exam/{exam_id}/assignments",
        headers=_headers(teacher_token),
        json={"student_ids": [student.id]},
    )
    detail = client.get(f"/api/exam/{exam_id}", headers=_headers(student_token)).json()
    question_id = detail["questions"][0]["id"]
    record_id = _start_exam(client, exam_id, student_token)
    _set_record_started_at(db, record_id, 2)  # 2 秒前开始，极速

    resp = client.post(
        f"/api/exam/{exam_id}/submit",
        headers=_headers(student_token),
        json={"exam_record_id": record_id, "answers": [{"question_id": question_id, "student_answer": "go"}]},
    )
    assert resp.status_code == 200, resp.text
    err = db.query(ErrorBook).filter(ErrorBook.student_id == student.id, ErrorBook.question_id == question_id).first()
    assert err is None, "极速交卷不应进错题本"
    record = db.get(ExamRecord, record_id)
    assert record.suspected_low_quality == 1
