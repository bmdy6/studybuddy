"""考试批次 API 集成测试。"""

import io
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.material import Material
from app.models.exam_batch import ExamBatch
from app.models.user import User
from app.core.auth import access_service
from app.utils.security import hash_password


def _headers(token: str) -> dict:
    """生成认证请求头。"""
    return {"Authorization": f"Bearer {token}"}


def _login(client: TestClient, username: str, password: str) -> dict:
    """登录并返回响应 JSON。"""
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _create_student(db: Session, display_name: str, teacher_id: int | None = 1) -> User:
    """创建一个事务内可回滚的测试学生，可选绑定给老师。"""
    student = User(
        username=f"student_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name=display_name,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    if teacher_id is not None:
        access_service.bind_teacher_student(db, teacher_id, student.id)
    return student


def _create_batch(client: TestClient, teacher_token: str, student_id: int) -> dict:
    """通过 API 为指定学生创建考试批次。"""
    r = client.post(
        "/api/exam-batches",
        headers=_headers(teacher_token),
        json={
            "student_id": student_id,
            "subject": "english",
            "exam_name": "批次测试",
            "exam_date": "2026-07-01",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_exam_batch_defaults_subject_to_auto(client: TestClient, db: Session):
    """拍题批改不要求用户预选学科，批次默认交给 AI 识别。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "自动识别学科学生")

    r = client.post(
        "/api/exam-batches",
        headers=_headers(teacher["access_token"]),
        json={
            "student_id": student.id,
            "exam_name": "微信图片批改",
            "exam_date": "2026-07-05",
        },
    )

    assert r.status_code == 201, r.text
    assert r.json()["subject"] == "auto"


def _local_upload_path(content_ref: str) -> str:
    """把 local: content_ref 转成本地上传文件路径。"""
    rel_path = content_ref.removeprefix("local:")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", rel_path)


def test_exam_batch_photo_upload_creates_material_record(client: TestClient, db: Session):
    """批次照片上传后会生成素材记录并写回 photo_material_ids。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "照片入库学生")
    batch = _create_batch(client, teacher["access_token"], student.id)
    uploaded_path: str | None = None

    try:
        r = client.post(
            f"/api/exam-batches/{batch['id']}/photos",
            headers=_headers(teacher["access_token"]),
            data={"page_type": "试卷"},
            files=[("files", ("page.jpg", io.BytesIO(b"jpg"), "image/jpeg"))],
        )

        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["photo_material_ids"]) == 1

        material = db.get(Material, data["photo_material_ids"][0])
        assert material is not None
        assert material.name == "01_试卷_第1页.jpg"
        assert material.type == "image"
        assert material.source == "teacher"
        assert material.uploaded_by == 1
        assert material.knowledge_tags == ["english"]
        assert material.content_ref is not None
        assert material.content_ref.startswith(f"local:materials/exams/{data['folder_name']}/")
        uploaded_path = _local_upload_path(material.content_ref)
        assert os.path.exists(uploaded_path)
    finally:
        if uploaded_path and os.path.exists(uploaded_path):
            os.remove(uploaded_path)
            folder = os.path.dirname(uploaded_path)
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)


def test_exam_batch_photo_upload_rejects_invalid_extension(client: TestClient, db: Session):
    """批次照片上传拒绝非图片扩展名。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "照片格式学生")
    batch = _create_batch(client, teacher["access_token"], student.id)

    r = client.post(
        f"/api/exam-batches/{batch['id']}/photos",
        headers=_headers(teacher["access_token"]),
        data={"page_type": "试卷"},
        files=[("files", ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream"))],
    )

    assert r.status_code == 415
    assert "照片格式" in r.json()["detail"]
    listed = client.get(
        "/api/exam-batches",
        headers=_headers(teacher["access_token"]),
        params={"student_id": student.id},
    )
    assert listed.status_code == 200, listed.text
    assert all(item["id"] != batch["id"] for item in listed.json())


def test_delete_empty_exam_batch(client: TestClient, db: Session):
    """上传失败留下的空批次可以清理。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "空批次学生")
    batch = _create_batch(client, teacher["access_token"], student.id)

    r = client.delete(f"/api/exam-batches/{batch['id']}", headers=_headers(teacher["access_token"]))

    assert r.status_code == 204, r.text
    assert db.get(ExamBatch, batch["id"]) is None


def test_delete_exam_batch_rejects_batch_with_photos(client: TestClient, db: Session):
    """已有照片的批次不能被空批次清理接口误删。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "非空批次学生")
    batch = _create_batch(client, teacher["access_token"], student.id)
    uploaded_path: str | None = None

    try:
        upload = client.post(
            f"/api/exam-batches/{batch['id']}/photos",
            headers=_headers(teacher["access_token"]),
            data={"page_type": "试卷"},
            files=[("files", ("page.jpg", io.BytesIO(b"jpg"), "image/jpeg"))],
        )
        assert upload.status_code == 200, upload.text
        material = db.get(Material, upload.json()["photo_material_ids"][0])
        assert material and material.content_ref
        uploaded_path = _local_upload_path(material.content_ref)

        r = client.delete(f"/api/exam-batches/{batch['id']}", headers=_headers(teacher["access_token"]))

        assert r.status_code == 409
        assert db.get(ExamBatch, batch["id"]) is not None
    finally:
        if uploaded_path and os.path.exists(uploaded_path):
            os.remove(uploaded_path)
            folder = os.path.dirname(uploaded_path)
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)


def test_student_cannot_operate_other_student_exam_batch(client: TestClient, db: Session):
    """学生不能操作不属于自己的考试批次。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _login(client, "student", "student123")
    other_student = _create_student(db, "另一个学生")
    batch = _create_batch(client, teacher["access_token"], other_student.id)
    student_headers = _headers(student["access_token"])

    photos = client.post(
        f"/api/exam-batches/{batch['id']}/photos",
        headers=student_headers,
        data={"page_type": "试卷"},
        files=[("files", ("page.jpg", io.BytesIO(b"jpg"), "image/jpeg"))],
    )
    synthesize = client.post(f"/api/exam-batches/{batch['id']}/synthesize", headers=student_headers)
    parse = client.post(f"/api/exam-batches/{batch['id']}/parse", headers=student_headers)
    grade = client.post(
        f"/api/exam-batches/{batch['id']}/grade",
        headers=student_headers,
        json={
            "grade_mode": "no_score_no_answer",
            "parsed_questions": [{"no": "1", "answer": "A"}],
        },
    )
    delete = client.delete(f"/api/exam-batches/{batch['id']}", headers=student_headers)

    assert photos.status_code == 403
    assert synthesize.status_code == 403
    assert parse.status_code == 403
    assert grade.status_code == 403
    assert delete.status_code == 403


def test_confirm_answer_review_persists_confirmed_answers(client: TestClient, db: Session):
    """确认拍题作答核对后，保留识别答案和学生修正答案。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "作答核对学生")
    batch = _create_batch(client, teacher["access_token"], student.id)
    model = db.get(ExamBatch, batch["id"])
    assert model is not None
    model.recognized_markdown = "1. 题目\n学生作答：D\n作答置信度：低"
    model.answer_review_state = {
        "batch_id": model.id,
        "recognized_markdown": model.recognized_markdown,
        "items": [
            {
                "question_no": "1",
                "detected_answer": "D",
                "confirmed_answer": None,
                "confidence": "low",
                "needs_review": True,
                "review_reason": "圈选痕迹太淡",
                "answer_type": "choice",
                "source_excerpt": "1. 题目",
                "skipped": False,
            }
        ],
        "status": "pending_review",
    }
    db.commit()

    r = client.post(
        f"/api/exam-batches/{batch['id']}/answer-review/confirm",
        headers=_headers(teacher["access_token"]),
        json={
            "items": [
                {
                    "question_no": "1",
                    "detected_answer": "D",
                    "confirmed_answer": "B",
                    "confidence": "low",
                    "needs_review": True,
                    "review_reason": "圈选痕迹太淡",
                    "answer_type": "choice",
                    "source_excerpt": "1. 题目",
                    "skipped": False,
                }
            ]
        },
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "confirmed"
    assert data["items"][0]["detected_answer"] == "D"
    assert data["items"][0]["confirmed_answer"] == "B"
    db.refresh(model)
    assert model.answer_review_state["items"][0]["confirmed_answer"] == "B"
    assert model.answer_review_confirmed_at is not None


def test_confirm_answer_review_rejects_unconfirmed_low_confidence_item(client: TestClient, db: Session):
    """低置信或看不清的作答，必须确认、跳过或标为空答。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "低置信学生")
    batch = _create_batch(client, teacher["access_token"], student.id)

    r = client.post(
        f"/api/exam-batches/{batch['id']}/answer-review/confirm",
        headers=_headers(teacher["access_token"]),
        json={
            "items": [
                {
                    "question_no": "1",
                    "detected_answer": "[?]",
                    "confirmed_answer": None,
                    "confidence": "low",
                    "needs_review": True,
                    "review_reason": "学生作答看不清",
                    "answer_type": "unknown",
                    "source_excerpt": "1. 题目",
                    "skipped": False,
                }
            ]
        },
    )

    assert r.status_code == 422
    assert "第1题" in r.json()["detail"]


def test_exam_batch_grade_rejects_invalid_grade_mode(client: TestClient, db: Session):
    """判分接口拒绝不在枚举内的 grade_mode。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "判分模式学生")
    batch = _create_batch(client, teacher["access_token"], student.id)

    r = client.post(
        f"/api/exam-batches/{batch['id']}/grade",
        headers=_headers(teacher["access_token"]),
        json={
            "grade_mode": "bad_mode",
            "parsed_questions": [{"no": "1", "answer": "A"}],
        },
    )

    assert r.status_code == 422


def test_teacher_cannot_create_exam_batch_for_unbound_student(client: TestClient, db: Session):
    """老师不能给未绑定学生创建错题导入批次。"""
    teacher = _login(client, "teacher", "teacher123")
    student = _create_student(db, "未绑定批次学生", teacher_id=None)

    r = client.post(
        "/api/exam-batches",
        headers=_headers(teacher["access_token"]),
        json={
            "student_id": student.id,
            "subject": "english",
            "exam_name": "越权批次",
            "exam_date": "2026-07-01",
        },
    )

    assert r.status_code == 403
