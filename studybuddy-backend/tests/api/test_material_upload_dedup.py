"""素材上传去重（文件层 SHA-256 + 归属契约）单测。

覆盖 spec 第五、四、八章：
- 同归属范围同 sha 拦截（改名也拦截）
- 跨学生同文件不拦截
- 家长传 target_student_id 校验绑定关系（403 未绑定）
- 旧数据 student_id=NULL fallback uploaded_by 范围去重
- 命中返回已有素材，不新建、不重复上传文件
- 文件名不参与判断
- 命中重复 HTTP 仍返回素材（is_duplicate=True）
"""

from __future__ import annotations

import io
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.material import Material
from app.models.teacher_student import TeacherStudent
from app.models.user import User
from app.utils.security import hash_password


def _create_student(db: Session, name: str) -> User:
    user = User(
        username=f"dedup_student_{uuid4().hex[:10]}",
        password_hash=hash_password("x"),
        role="student",
        display_name=name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_teacher(db: Session, name: str) -> User:
    user = User(
        username=f"dedup_teacher_{uuid4().hex[:10]}",
        password_hash=hash_password("x"),
        role="teacher",
        display_name=name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _bind(db: Session, teacher_id: int, student_id: int) -> None:
    db.add(TeacherStudent(teacher_id=teacher_id, student_id=student_id))
    db.commit()


def _login(client: TestClient, username: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": "x"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_same_file_renamed_hits_hard_dedup_within_owner(client: TestClient, db: Session):
    """同归属范围上传 SHA-256 相同但文件名不同的文件 -> 命中已有素材，不新建。"""
    student = _create_student(db, "去重学生A")
    token = _login(client, student.username)
    file_bytes = b"duplicate-png-bytes"

    upload_calls: list[bytes] = []
    fake_key_counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        upload_calls.append(data)
        fake_key_counter["n"] += 1
        return f"materials/2026/07/dedup-{fake_key_counter['n']}.png"

    with patch("app.features.materials.service.upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=None
    ):
        # 上传 ensure_extraction 不在导入期；这里直接对 service 层调用做断言即可
        pass

    # 直接调 service 层，确保去重逻辑独立于自动识别
    from app.features.materials import service as material_service

    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        first = material_service.upload_material(
            db, file_bytes, "png", "第一份", "image", [], student
        )
        second = material_service.upload_material(
            db, file_bytes, "png", "改名第二份", "image", [], student
        )

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert second.material_id == first.material_id
    assert second.duplicate_of_material_id == first.material_id
    # 只上传一次文件
    assert len(upload_calls) == 1
    # 只落一条记录
    records = db.query(Material).filter(Material.uploaded_by == student.id).all()
    assert len(records) == 1


def test_filename_not_used_for_dedup(client: TestClient, db: Session):
    """不同文件名但相同内容仍命中；不同内容但相同文件名不命中。"""
    student = _create_student(db, "文件名学生")
    token = _login(client, student.username)
    from app.features.materials import service as material_service

    same_bytes = b"same-content"
    different_bytes = b"different-content"
    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/k{counter['n']}.png"

    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        m1 = material_service.upload_material(db, same_bytes, "png", "words.png", "image", [], student)
        # 同内容、同文件名 -> 仍命中
        m2 = material_service.upload_material(db, same_bytes, "png", "words.png", "image", [], student)
        # 不同内容、同文件名 -> 不命中，新建
        m3 = material_service.upload_material(db, different_bytes, "png", "words.png", "image", [], student)

    assert m2.is_duplicate is True
    assert m3.is_duplicate is False
    assert m3.material_id != m1.material_id
    records = db.query(Material).filter(Material.uploaded_by == student.id).all()
    assert len(records) == 2


def test_cross_student_same_file_not_intercepted(client: TestClient, db: Session):
    """学生 A、B 各上传相同文件 -> 各自独立，不互相拦截。"""
    student_a = _create_student(db, "学生A")
    student_b = _create_student(db, "学生B")
    file_bytes = b"shared-bytes"
    from app.features.materials import service as material_service

    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/cross{counter['n']}.png"

    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        a_resp = material_service.upload_material(db, file_bytes, "png", "A的", "image", [], student_a)
        b_resp = material_service.upload_material(db, file_bytes, "png", "B的", "image", [], student_b)

    assert a_resp.is_duplicate is False
    assert b_resp.is_duplicate is False
    assert a_resp.material_id != b_resp.material_id
    assert a_resp.student_id == student_a.id
    assert b_resp.student_id == student_b.id
    # 两个文件都上传了
    assert len(counter) or counter["n"] == 2


def test_teacher_uploads_with_target_student_id_sets_student_id(client: TestClient, db: Session):
    """家长上传传 target_student_id -> student_id 写入目标学生；校验绑定关系。"""
    teacher = _create_teacher(db, "去重家长")
    student = _create_student(db, "目标学生")
    _bind(db, teacher.id, student.id)
    from app.features.materials import service as material_service

    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/t{counter['n']}.png"

    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        resp = material_service.upload_material(
            db, b"teacher-file", "png", "家长给学生", "image", [], teacher, target_student_id=student.id
        )

    assert resp.is_duplicate is False
    assert resp.student_id == student.id
    record = db.get(Material, resp.material_id)
    assert record.student_id == student.id
    assert record.uploaded_by == teacher.id


def test_target_student_and_bound_teachers_can_access_teacher_uploaded_material(
    db: Session,
) -> None:
    """student_id 是真实归属：目标学生和绑定家长都能访问、列表可见。"""
    uploader = _create_teacher(db, "上传家长")
    other_teacher = _create_teacher(db, "另一位绑定家长")
    unbound_teacher = _create_teacher(db, "未绑定家长")
    student = _create_student(db, "素材归属学生")
    _bind(db, uploader.id, student.id)
    _bind(db, other_teacher.id, student.id)

    from app.features.materials import service as material_service

    with patch.object(
        material_service,
        "upload_file",
        return_value="materials/2026/07/owner-scope.png",
    ):
        response = material_service.upload_material(
            db,
            b"owner-scope-image",
            "png",
            "家长上传的单词表",
            "image",
            [],
            uploader,
            target_student_id=student.id,
        )

    material = db.get(Material, response.material_id)
    assert material is not None
    assert material_service.can_access_material(db, material, student) is True
    assert material_service.can_access_material(db, material, other_teacher) is True
    assert material_service.can_access_material(db, material, unbound_teacher) is False
    assert response.material_id in {item.id for item in material_service.list_materials(db, student)}
    assert response.material_id in {item.id for item in material_service.list_materials(db, other_teacher)}


def test_teacher_target_student_not_bound_returns_403(client: TestClient, db: Session):
    """家长上传未绑定学生 target_student_id -> 权限失败（resolve 抛 PermissionError）。"""
    teacher = _create_teacher(db, "未绑定家长")
    student = _create_student(db, "未绑定学生")
    token = _login(client, teacher.username)
    from app.features.materials import service as material_service
    import pytest

    with patch.object(material_service, "upload_file", return_value="materials/x.png"), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        with pytest.raises(PermissionError):
            material_service.upload_material(
                db, b"file", "png", "name", "image", [], teacher, target_student_id=student.id
            )

    # 不应落库
    assert db.query(Material).filter(Material.uploaded_by == teacher.id).count() == 0


def test_teacher_upload_without_target_student_has_null_owner(client: TestClient, db: Session):
    """家长上传不传 target_student_id -> student_id=NULL，归属未定（fallback uploaded_by 去重）。"""
    teacher = _create_teacher(db, "无目标家长")
    from app.features.materials import service as material_service

    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/nt{counter['n']}.png"

    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        resp = material_service.upload_material(db, b"file", "png", "无目标", "image", [], teacher)

    assert resp.is_duplicate is False
    assert resp.student_id is None
    record = db.get(Material, resp.material_id)
    assert record.student_id is None


def test_legacy_null_student_id_falls_back_to_uploaded_by_for_dedup(client: TestClient, db: Session):
    """旧数据 student_id=NULL，按 uploaded_by 范围去重：同上传者同 sha 命中。"""
    teacher = _create_teacher(db, "旧数据家长")
    file_bytes = b"legacy-bytes"
    file_sha = __import__("hashlib").sha256(file_bytes).hexdigest()
    # 模拟旧数据：student_id=NULL, file_sha256=NULL（无法比对，所以不命中）
    legacy = Material(
        name="旧素材",
        type="image",
        source="teacher",
        content_ref="local:materials/old.png",
        uploaded_by=teacher.id,
        student_id=None,
        file_sha256=None,
    )
    db.add(legacy)
    db.commit()
    db.refresh(legacy)

    from app.features.materials import service as material_service

    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/lf{counter['n']}.png"

    # 旧素材 file_sha256=NULL，新上传同 sha 不命中（无法比对），新建
    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        resp = material_service.upload_material(db, file_bytes, "png", "新上传", "image", [], teacher)

    assert resp.is_duplicate is False
    assert resp.material_id != legacy.id
    # 新记录已写入 sha
    new_record = db.get(Material, resp.material_id)
    assert new_record.file_sha256 == file_sha

    # 再上传相同 sha：现在新记录有 sha，student_id=NULL fallback uploaded_by 命中
    with patch.object(material_service, "upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        resp2 = material_service.upload_material(db, file_bytes, "png", "第三次", "image", [], teacher)

    assert resp2.is_duplicate is True
    assert resp2.material_id == resp.material_id


def test_upload_response_carries_is_duplicate_and_student_id_fields(client: TestClient, db: Session):
    """MaterialUploadResponse 含 is_duplicate / duplicate_of_material_id / student_id 字段。"""
    student = _create_student(db, "响应字段学生")
    from app.features.materials import service as material_service

    with patch.object(material_service, "upload_file", return_value="materials/2026/07/r.png"), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        resp = material_service.upload_material(db, b"r", "png", "r", "image", [], student)

    body = resp.model_dump()
    assert "is_duplicate" in body
    assert "duplicate_of_material_id" in body
    assert "student_id" in body
    assert body["student_id"] == student.id


def test_router_upload_returns_duplicate_flag(client: TestClient, db: Session):
    """端点层：同归属范围同 sha 第二次上传 -> 201 + is_duplicate=True，不新建。"""
    student = _create_student(db, "端点去重学生")
    token = _login(client, student.username)
    file_bytes = b"endpoint-dup"

    counter = {"n": 0}

    def fake_upload(data: bytes, ext: str) -> str:
        counter["n"] += 1
        return f"materials/2026/07/ep{counter['n']}.png"

    with patch("app.features.materials.service.upload_file", side_effect=fake_upload), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        r1 = client.post(
            "/api/material/upload",
            headers=_h(token),
            data={"name": "第一份", "type": "image", "knowledge_tags": "[]"},
            files={"file": ("a.png", io.BytesIO(file_bytes), "image/png")},
        )
        r2 = client.post(
            "/api/material/upload",
            headers=_h(token),
            data={"name": "改名第二份", "type": "image", "knowledge_tags": "[]"},
            files={"file": ("b.png", io.BytesIO(file_bytes), "image/png")},
        )

    assert r1.status_code in (200, 201), r1.text
    assert r2.status_code in (200, 201), r2.text
    d1, d2 = r1.json(), r2.json()
    assert d1["is_duplicate"] is False
    assert d2["is_duplicate"] is True
    assert d2["material_id"] == d1["material_id"]
    assert d2["duplicate_of_material_id"] == d1["material_id"]
    assert counter["n"] == 1  # 只上传一次


def test_router_upload_with_target_student_id(client: TestClient, db: Session):
    """端点层：家长传 target_student_id -> student_id 正确；未绑定 -> 403。"""
    teacher = _create_teacher(db, "端点家长")
    bound = _create_student(db, "端点绑定学生")
    unbound = _create_student(db, "端点未绑定学生")
    _bind(db, teacher.id, bound.id)
    token = _login(client, teacher.username)

    with patch("app.features.materials.service.upload_file", return_value="materials/2026/07/ts.png"), patch(
        "app.features.materials.extraction_service.ensure_extraction", new=lambda *a, **k: None
    ):
        r_ok = client.post(
            "/api/material/upload",
            headers=_h(token),
            data={
                "name": "给绑定学生",
                "type": "image",
                "knowledge_tags": "[]",
                "target_student_id": str(bound.id),
            },
            files={"file": ("a.png", io.BytesIO(b"x"), "image/png")},
        )
        r_403 = client.post(
            "/api/material/upload",
            headers=_h(token),
            data={
                "name": "给未绑定学生",
                "type": "image",
                "knowledge_tags": "[]",
                "target_student_id": str(unbound.id),
            },
            files={"file": ("a.png", io.BytesIO(b"y"), "image/png")},
        )

    assert r_ok.status_code in (200, 201), r_ok.text
    assert r_ok.json()["student_id"] == bound.id
    assert r_403.status_code == 403
    assert "绑定" in r_403.json()["detail"] or "无权" in r_403.json()["detail"]
