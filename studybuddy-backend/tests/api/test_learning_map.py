from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.error_book import ErrorBook
from app.models.exam import Exam
from app.models.exam_record import ExamRecord
from app.models.question import Question
from app.models.user import User
from app.utils.security import hash_password


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_error(db: Session, student_id: int = 2) -> None:
    exam = Exam(title="学习地图接口测试卷", subject="math", status="published", created_by=1)
    db.add(exam)
    db.flush()
    record = ExamRecord(exam_id=exam.id, student_id=student_id, status="graded")
    db.add(record)
    db.flush()
    question = Question(
        exam_id=exam.id,
        type="single_choice",
        stem="分数应用题",
        options=["A", "B"],
        answer_json="A",
        score=Decimal("2.00"),
        knowledge_tags=["分数应用题"],
    )
    db.add(question)
    db.flush()
    db.add(
        ErrorBook(
            student_id=student_id,
            question_id=question.id,
            exam_record_id=record.id,
            knowledge_tags=["分数应用题"],
            error_count=3,
        )
    )
    db.commit()


def _create_unbound_student(db: Session) -> User:
    student = User(
        username=f"map_unbound_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name="学习地图未绑定学生",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_bound_teacher_can_read_student_learning_map(client: TestClient, db: Session):
    _seed_error(db)
    token = _login(client, "teacher", "teacher123")

    response = client.get("/api/students/2/learning-map", headers=_headers(token))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["student_id"] == 2
    assert data["summary"]["weak"] >= 1
    assert data["total_count"] >= 1
    assert data["has_more"] is False
    node = next(item for item in data["nodes"] if item["tag"] == "分数应用题")
    assert node["status"] == "weak"
    assert node["error_count"] == 3


def test_learning_map_summary_counts_all_nodes_before_truncation(client: TestClient, db: Session):
    """summary/total_count 基于全量节点统计，不受 limit 截断影响；超限时 has_more=True。"""
    for i in range(35):
        exam = Exam(title=f"地图截断测试卷{i}", subject="math", status="published", created_by=1)
        db.add(exam)
        db.flush()
        record = ExamRecord(exam_id=exam.id, student_id=2, status="graded")
        db.add(record)
        db.flush()
        question = Question(
            exam_id=exam.id,
            type="single_choice",
            stem=f"截断知识点{i}",
            options=["A", "B"],
            answer_json="A",
            score=Decimal("2.00"),
            knowledge_tags=[f"截断知识点{i}"],
        )
        db.add(question)
        db.flush()
        db.add(
            ErrorBook(
                student_id=2,
                question_id=question.id,
                exam_record_id=record.id,
                knowledge_tags=[f"截断知识点{i}"],
                error_count=1,
            )
        )
    db.commit()
    token = _login(client, "teacher", "teacher123")

    response = client.get("/api/students/2/learning-map", headers=_headers(token))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_count"] >= 35  # 35 个新节点（本测试未 seed 既有）
    assert data["has_more"] is True  # 超过默认 limit=30
    assert len(data["nodes"]) == 30
    # summary 统计全量而非截断后的 30 个
    assert sum(data["summary"].values()) == data["total_count"]


def test_teacher_cannot_read_unbound_student_learning_map(client: TestClient, db: Session):
    student = _create_unbound_student(db)
    _seed_error(db, student.id)
    token = _login(client, "teacher", "teacher123")

    response = client.get(f"/api/students/{student.id}/learning-map", headers=_headers(token))

    assert response.status_code == 403
