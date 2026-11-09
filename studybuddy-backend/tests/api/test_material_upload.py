"""素材上传与列表、健康检查集成测试。

COS 真实上传不在 CI 范围（无凭据），upload_file 用 monkeypatch mock。
"""

import io
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.main import app
from app.models.material import Material
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.features.materials import service as material_service
from app.features.materials.markdown_extraction_service import MarkdownExtractionResult
from app.utils.security import hash_password


@contextmanager
def _count_queries(db: Session) -> Iterator[Callable[[], int]]:
    """统计当前测试连接执行的 SQL 条数。"""
    count = 0
    connection = db.connection()

    def _increment(*_args: object) -> None:
        """记录一次 SQL 执行。"""
        nonlocal count
        count += 1

    event.listen(connection, "before_cursor_execute", _increment)
    try:
        yield lambda: count
    finally:
        event.remove(connection, "before_cursor_execute", _increment)


def _create_upload_user(db: Session, display_name: str) -> User:
    """创建一个可回滚的素材上传用户。"""
    user = User(
        username=f"material_user_{uuid4().hex[:12]}",
        password_hash=hash_password("student123"),
        role="student",
        display_name=display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _bind_teacher_student(db: Session, teacher_id: int, student_id: int) -> None:
    db.add(TeacherStudent(teacher_id=teacher_id, student_id=student_id))
    db.commit()


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


def test_upload_material_mocked(client: TestClient, db: Session):
    """上传素材：mock COS 返回固定 cos_key，验证落库 + 响应。"""
    tt = _teacher_token(client)
    fake_key = "materials/2026/06/fakeuuid123.png"

    with patch("app.features.materials.service.upload_file", return_value=fake_key):
        r = client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={
                "name": "U5单词卡",
                "type": "image",
                "knowledge_tags": '["过去时", "动词"]',
            },
            files={"file": ("card.png", io.BytesIO(b"fakepng"), "image/png")},
        )
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["cos_key"] == fake_key
    assert data["name"] == "U5单词卡"
    assert data["type"] == "image"
    assert data["source"] == "teacher"
    assert data["material_id"] > 0
    material = db.get(Material, data["material_id"])
    assert material is not None
    assert material.knowledge_tags == ["过去时", "动词"]


def test_upload_material_normalizes_tags(client: TestClient, db: Session):
    """上传素材时清理空标签和重复标签。"""
    tt = _teacher_token(client)
    fake_key = "materials/2026/06/normalized-tags.png"

    with patch("app.features.materials.service.upload_file", return_value=fake_key):
        r = client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={
                "name": "标签归一化",
                "type": "image",
                "knowledge_tags": '[" 过去时 ", "", "过去时", "动词"]',
            },
            files={"file": ("card.png", io.BytesIO(b"fakepng"), "image/png")},
        )

    assert r.status_code == 201, r.text
    material = db.get(Material, r.json()["material_id"])
    assert material is not None
    assert material.knowledge_tags == ["过去时", "动词"]


@pytest.mark.parametrize("knowledge_tags", ["not-json", '{"tag": "过去时"}', '["过去时", 123]'])
def test_upload_material_rejects_invalid_tags(client: TestClient, knowledge_tags: str):
    """素材标签必须是 JSON 字符串数组。"""
    tt = _teacher_token(client)
    upload_mock = Mock(return_value="materials/should-not-upload.png")

    with patch("app.features.materials.service.upload_file", upload_mock):
        r = client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={"name": "坏标签", "type": "image", "knowledge_tags": knowledge_tags},
            files={"file": ("card.png", io.BytesIO(b"fakepng"), "image/png")},
        )

    assert r.status_code == 422
    assert "knowledge_tags" in r.json()["detail"]
    upload_mock.assert_not_called()


def test_upload_material_cos_failure(client: TestClient):
    """COS 上传失败 → 422，不落库。"""
    tt = _teacher_token(client)
    with patch(
        "app.features.materials.service.upload_file",
        side_effect=RuntimeError("COS 熔断中"),
    ):
        r = client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={"name": "失败素材", "type": "other", "knowledge_tags": "[]"},
            files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
        )
    assert r.status_code == 422
    assert "COS" in r.json()["detail"]


def test_upload_material_rejects_invalid_extension(client: TestClient):
    """素材上传在调用存储前拒绝非白名单扩展名。"""
    tt = _teacher_token(client)
    upload_mock = Mock(return_value="materials/should-not-upload.exe")

    with patch("app.features.materials.service.upload_file", upload_mock):
        r = client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={"name": "可疑素材", "type": "other", "knowledge_tags": "[]"},
            files={"file": ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        )

    assert r.status_code == 415
    assert "素材格式" in r.json()["detail"]
    upload_mock.assert_not_called()


def test_list_materials(client: TestClient):
    """上传后列表能查到，且返回 cos_url。"""
    tt = _teacher_token(client)
    fake_key = "materials/2026/06/listitem.png"
    with patch("app.features.materials.service.upload_file", return_value=fake_key):
        client.post(
            "/api/material/upload",
            headers=_h(tt),
            data={"name": "列表项", "type": "image", "knowledge_tags": '["测试"]'},
            files={"file": ("a.png", io.BytesIO(b"png"), "image/png")},
        )

    r = client.get("/api/material", headers=_h(tt))
    assert r.status_code == 200, r.text
    items = r.json()
    matched = [i for i in items if i["name"] == "列表项"]
    assert len(matched) >= 1
    item = matched[0]
    assert "cos_url" in item
    assert fake_key in item["cos_url"]
    assert item["knowledge_tags"] == ["测试"]


def test_list_materials_student_only_own(client: TestClient):
    """学生只能看自己上传的素材。"""
    st = _student_token(client)
    fake_key = "materials/2026/06/studentown.png"
    with patch("app.features.materials.service.upload_file", return_value=fake_key):
        client.post(
            "/api/material/upload",
            headers=_h(st),
            data={"name": "学生素材", "type": "image", "knowledge_tags": "[]"},
            files={"file": ("s.png", io.BytesIO(b"png"), "image/png")},
        )
    r = client.get("/api/material", headers=_h(st))
    assert r.status_code == 200
    items = r.json()
    # 学生素材应出现
    assert any(i["name"] == "学生素材" for i in items)


def test_preview_url_rejects_other_user_material(client: TestClient, db: Session):
    """学生不能按 id 预览老师上传的素材。"""
    tt = _teacher_token(client)
    st = _student_token(client)
    teacher = db.query(User).filter(User.username == "teacher").one()
    material = Material(
        name="老师私有素材",
        type="image",
        source="teacher",
        content_ref="local:materials/private.png",
        knowledge_tags=[],
        uploaded_by=teacher.id,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    teacher_preview = client.get(f"/api/material/{material.id}/preview-url", headers=_h(tt))
    assert teacher_preview.status_code == 200, teacher_preview.text

    student_preview = client.get(f"/api/material/{material.id}/preview-url", headers=_h(st))
    assert student_preview.status_code == 403


def test_material_recognize_requires_access(client: TestClient, db: Session):
    owner = _create_upload_user(db, "别人的素材上传者")
    material = Material(
        name="别人的素材",
        type="image",
        source="student",
        content_ref="local:materials/private.png",
        uploaded_by=owner.id,
    )
    db.add(material)
    db.commit()

    headers = _h(_student_token(client))
    resp = client.post(f"/api/material/{material.id}/recognize", headers=headers)

    assert resp.status_code == 403


def test_material_confirm_extraction_saves_confirmed_markdown(client: TestClient, db: Session):
    student = db.query(User).filter(User.username == "student").one()
    material = Material(
        name="单词表",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        recognized_markdown="### 单词表\n\napple 苹果",
        recognition_status="recognized",
    )
    db.add(material)
    db.commit()

    headers = _h(_student_token(client))
    resp = client.put(
        f"/api/material/{material.id}/extraction/confirm",
        json={"confirmed_markdown": "### 单词表\n\napple 苹果\nbanana 香蕉"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["recognition_status"] == "confirmed"
    assert "banana 香蕉" in body["confirmed_markdown"]


def test_material_confirm_extraction_rejects_blank_after_trim(client: TestClient, db: Session):
    """确认稿去掉空白后不能为空，否则会产生已确认但无内容的矛盾状态。"""
    student = db.query(User).filter(User.username == "student").one()
    material = Material(
        name="空白确认稿",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        recognized_markdown="### 单词表\n\napple 苹果",
        recognition_status="recognized",
    )
    db.add(material)
    db.commit()

    resp = client.put(
        f"/api/material/{material.id}/extraction/confirm",
        json={"confirmed_markdown": "   "},
        headers=_h(_student_token(client)),
    )

    assert resp.status_code == 422
    assert "确认稿不能为空" in resp.json()["detail"]
    db.refresh(material)
    assert material.recognition_status == "recognized"
    assert material.confirmed_markdown is None


def test_material_recognize_uses_markdown_extraction_service(client: TestClient, db: Session, tmp_path, monkeypatch):
    """素材识别应复用通用 Markdown 识别服务，并落库识别稿。"""
    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    material_dir = upload_root / "materials"
    material_dir.mkdir(parents=True)
    image_path = material_dir / "words.png"
    image_path.write_bytes(b"fake-image")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    material = Material(
        name="单词表",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    result = MarkdownExtractionResult(
        markdown="### 单词表\n\napple 苹果",
        raw_text="### 单词表\n\napple 苹果",
        confidence="high",
        content_type="英语单词表",
        provider="mimo",
        elapsed_ms=120,
    )
    with patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown",
        new_callable=AsyncMock,
        return_value=result,
    ) as recognize_mock:
        resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 200, resp.text
    recognize_mock.assert_awaited_once()
    assert recognize_mock.await_args.args == ([str(image_path)],)
    assert recognize_mock.await_args.kwargs == {"mode": "learning_material"}
    body = resp.json()
    assert body["recognition_status"] == "recognized"
    assert body["recognized_markdown"] == "### 单词表\n\napple 苹果"
    assert body["recognition_provider"] == "mimo"
    assert body["recognition_confidence"] == "high"
    assert body["content_type"] == "英语单词表"


def test_material_recognize_clears_stale_confirmation(client: TestClient, db: Session, tmp_path, monkeypatch):
    """重新识别素材时保留旧确认稿（spec 6.1/7.2：force 重识别不清空 confirmed）。

    历史 confirmed_markdown 继续优先于机器识别稿；重新识别只刷新 recognized_markdown。
    """
    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    material_dir = upload_root / "materials"
    material_dir.mkdir(parents=True)
    image_path = material_dir / "words.png"
    image_path.write_bytes(b"fake-image")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    material = Material(
        name="重新识别单词表",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        recognized_markdown="### 旧识别稿",
        confirmed_markdown="### 旧确认稿",
        recognition_status="confirmed",
    )
    db.add(material)
    db.commit()

    result = MarkdownExtractionResult(
        markdown="### 新识别稿\n\nbanana 香蕉",
        raw_text="### 新识别稿\n\nbanana 香蕉",
        confidence="medium",
        content_type="英语单词表",
        provider="mimo",
        uncertain_points=["banana 是否识别正确"],
    )
    with patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown",
        new_callable=AsyncMock,
        return_value=result,
    ):
        resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recognition_status"] == "needs_review"
    assert body["recognized_markdown"] == "### 新识别稿\n\nbanana 香蕉"
    # force 重识别保留 confirmed_markdown（spec 6.1/7.2），不清空
    assert body["confirmed_markdown"] == "### 旧确认稿"
    db.refresh(material)
    assert material.confirmed_markdown == "### 旧确认稿"


def test_material_recognize_unprocessable_file_returns_422(client: TestClient, db: Session):
    """素材存在但当前无法识别时返回 422，而不是误导成资源不存在。"""
    student = db.query(User).filter(User.username == "student").one()
    material = Material(
        name="远程素材",
        type="image",
        source="student",
        content_ref="cos:materials/words.png",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 422
    assert "不可识别" in resp.json()["detail"]


def test_material_recognize_local_scanned_pdf_returns_422(client: TestClient, db: Session, tmp_path, monkeypatch):
    """本地扫描/图像型 PDF（提取返回 None）-> 422 需人工确认，不 500。"""
    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    material_dir = upload_root / "materials"
    material_dir.mkdir(parents=True)
    pdf_path = material_dir / "handout.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))
    monkeypatch.setattr("app.core.pdf_service.extract_pdf_markdown", lambda _p: None)

    material = Material(
        name="讲义 PDF",
        type="pdf",
        source="student",
        content_ref="local:materials/handout.pdf",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]


def test_material_recognize_local_text_pdf_succeeds(client: TestClient, db: Session, tmp_path, monkeypatch):
    """本地文本型 PDF（提取成功）-> 识别成功，provider=pdf_inspector。"""
    from app.core.pdf_service import PdfExtractionResult

    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    material_dir = upload_root / "materials"
    material_dir.mkdir(parents=True)
    pdf_path = material_dir / "handout.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))
    monkeypatch.setattr(
        "app.core.pdf_service.extract_pdf_markdown",
        lambda _p: PdfExtractionResult(
            pdf_type="text_based",
            markdown="# 一元一次方程单元测试\n\n1. 解方程：2x + 3 = 7\n",
            has_encoding_issues=False,
            elapsed_ms=7,
        ),
    )

    material = Material(
        name="讲义 PDF",
        type="pdf",
        source="student",
        content_ref="local:materials/handout.pdf",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 200
    assert resp.json()["recognition_provider"] == "pdf_inspector"
    assert "一元一次方程单元测试" in resp.json()["recognized_markdown"]
    assert resp.json()["recognition_status"] in {"recognized", "needs_review"}


def test_material_recognize_missing_local_file_returns_422(client: TestClient, db: Session, tmp_path, monkeypatch):
    """素材记录存在但本地文件缺失时返回 422，提示可重试/重传。"""
    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    (upload_root / "materials").mkdir(parents=True)
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    material = Material(
        name="缺失文件",
        type="image",
        source="student",
        content_ref="local:materials/missing.png",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 422
    assert "素材文件不存在" in resp.json()["detail"]


def test_material_recognize_missing_material_returns_404(client: TestClient):
    """素材 id 不存在仍然返回 404。"""
    resp = client.post("/api/material/999999999/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 404
    assert "素材不存在" in resp.json()["detail"]


def test_material_recognize_failure_marks_failed(client: TestClient, db: Session, tmp_path, monkeypatch):
    """素材识别失败不应 500，状态回到可重试的失败态（spec 6.4/12：识别异常 -> failed）。

    OCR/LLM 失败属瞬时故障，ensure_extraction 捕获后置 status=failed（auto_ready=0），
    返回 200 + failed 状态，用户可手动重识别；不抛 422。
    """
    student = db.query(User).filter(User.username == "student").one()
    upload_root = tmp_path / "uploads"
    material_dir = upload_root / "materials"
    material_dir.mkdir(parents=True)
    image_path = material_dir / "broken.png"
    image_path.write_bytes(b"fake-image")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    material = Material(
        name="坏图片",
        type="image",
        source="student",
        content_ref="local:materials/broken.png",
        uploaded_by=student.id,
    )
    db.add(material)
    db.commit()

    with patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown",
        new_callable=AsyncMock,
        side_effect=RuntimeError("OCR timeout"),
    ):
        resp = client.post(f"/api/material/{material.id}/recognize", headers=_h(_student_token(client)))

    assert resp.status_code == 200, resp.text
    assert resp.json()["recognition_status"] == "failed"
    db.refresh(material)
    assert material.recognition_status == "failed"
    assert material.auto_ready is False


def test_get_material_extraction_requires_access(client: TestClient, db: Session):
    """素材识别详情沿用素材访问权限。"""
    owner = _create_upload_user(db, "识别详情上传者")
    material = Material(
        name="别人的识别稿",
        type="image",
        source="student",
        content_ref="local:materials/private.png",
        uploaded_by=owner.id,
        recognized_markdown="### 私有内容",
        recognition_status="recognized",
    )
    db.add(material)
    db.commit()

    resp = client.get(f"/api/material/{material.id}/extraction", headers=_h(_student_token(client)))

    assert resp.status_code == 403


def test_list_materials_returns_recognition_status(client: TestClient, db: Session):
    """素材列表需要给前端展示识别状态。"""
    teacher = db.query(User).filter(User.username == "teacher").one()
    material = Material(
        name="已识别素材",
        type="image",
        source="teacher",
        content_ref="local:materials/recognized.png",
        uploaded_by=teacher.id,
        recognition_status="recognized",
    )
    db.add(material)
    db.commit()

    resp = client.get("/api/material", headers=_h(_teacher_token(client)))

    assert resp.status_code == 200, resp.text
    item = next(item for item in resp.json() if item["name"] == "已识别素材")
    assert item["recognition_status"] == "recognized"


def test_teacher_material_access_limited_to_bound_students(client: TestClient, db: Session):
    """家长只能预览绑定学生上传的素材，不能看未绑定学生素材。"""
    tt = _teacher_token(client)
    teacher = db.query(User).filter(User.username == "teacher").one()
    bound_student = _create_upload_user(db, "绑定学生")
    unbound_student = _create_upload_user(db, "未绑定学生")
    _bind_teacher_student(db, teacher.id, bound_student.id)

    bound_material = Material(
        name="绑定学生素材",
        type="image",
        source="student",
        content_ref="local:materials/bound.png",
        knowledge_tags=[],
        uploaded_by=bound_student.id,
    )
    unbound_material = Material(
        name="未绑定学生素材",
        type="image",
        source="student",
        content_ref="local:materials/unbound.png",
        knowledge_tags=[],
        uploaded_by=unbound_student.id,
    )
    db.add_all([bound_material, unbound_material])
    db.commit()
    db.refresh(bound_material)
    db.refresh(unbound_material)

    assert client.get(f"/api/material/{bound_material.id}/preview-url", headers=_h(tt)).status_code == 200
    assert client.get(f"/api/material/{unbound_material.id}/preview-url", headers=_h(tt)).status_code == 403


def test_list_materials_normalizes_legacy_exam_photo_ref(client: TestClient, db: Session):
    """素材列表兼容旧版错题照片 local:exams 路径。"""
    tt = _teacher_token(client)
    teacher = db.query(User).filter(User.username == "teacher").one()
    db.add(
        Material(
            name="旧错题照片",
            type="image",
            source="teacher",
            content_ref="local:exams/batch-1/01_试卷_第1页.jpg",
            knowledge_tags=["english"],
            uploaded_by=teacher.id,
        )
    )
    db.commit()

    r = client.get("/api/material", headers=_h(tt))

    assert r.status_code == 200, r.text
    item = next(item for item in r.json() if item["name"] == "旧错题照片")
    assert item["cos_url"] == "/uploads/materials/exams/batch-1/01_试卷_第1页.jpg"


def test_build_url_uses_default_upload_base_path():
    """本地开发默认仍使用 /uploads，避免破坏 Vite 代理和本地预览。"""
    from app.features.materials.service import _build_url

    assert _build_url("local:materials/2026/07/demo.jpg") == "/uploads/materials/2026/07/demo.jpg"


def test_build_url_uses_configured_public_upload_base_path(monkeypatch):
    """线上可通过 /sb/uploads 公网前缀访问本地上传文件。"""
    from app.config import settings
    from app.features.materials.service import _build_url

    monkeypatch.setattr(settings, "PUBLIC_UPLOAD_BASE_PATH", "/sb/uploads")

    assert _build_url("local:materials/2026/07/demo.jpg") == "/sb/uploads/materials/2026/07/demo.jpg"


def test_list_materials_batches_uploaders_without_n_plus_one(client: TestClient, db: Session):
    """素材列表批量带出上传者名称，避免按素材逐条查 User。"""
    tt = _teacher_token(client)
    uploaders = [_create_upload_user(db, f"上传者{i}") for i in range(4)]
    teacher = db.query(User).filter(User.username == "teacher").one()
    for index, uploader in enumerate(uploaders):
        _bind_teacher_student(db, teacher.id, uploader.id)
        db.add(
            Material(
                name=f"批量素材{index}",
                type="image",
                source="student",
                content_ref=f"local:materials/query-count-{index}.png",
                knowledge_tags=["查询计数"],
                uploaded_by=uploader.id,
            )
        )
    db.commit()

    with _count_queries(db) as count:
        r = client.get("/api/material", headers=_h(tt))

    assert r.status_code == 200, r.text
    assert all(any(item["name"] == f"批量素材{index}" for item in r.json()) for index in range(4))
    assert count() <= 3


def test_health(client: TestClient):
    """健康检查：DB ok（测试库连通），COS 可能 degraded 但仍 200。"""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["db"] == "ok"
    assert data["status"] in ("ok", "degraded")


def test_root_and_trace_id(client: TestClient):
    """根路径 + trace_id 回写。"""
    r = client.get("/")
    assert r.status_code == 200
    assert "知了" in r.json()["name"]
    assert "x-trace-id" in {k.lower() for k in r.headers.keys()}
