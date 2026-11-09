"""素材自动识别、auto_ready 与内容指纹归一单测。

覆盖 spec 第六、八章：
- ensure_extraction 幂等（已 recognized 不重识别；processing 返回当前；force=True 重识别且不清 confirmed）
- 上传不触发识别（懒触发，由 read_material 首次读取时识别）
- 高置信非空 -> auto_ready=True，Agent 可读
- 低置信/有 uncertain -> auto_ready=False，needs_review
- 空 OCR / 失败 -> status=failed，auto_ready=0，read_material 不返回内容
- content_fingerprint 命中 -> duplicate_of_material_id 归一，列表只显规范素材，read_material 归一
- 近似内容只提示，不写精确关系
- COS 临时下载识别
- confirmed_markdown 优先级不变
- read_material auto_ready 分支 needs_confirmation=False

async 服务调用用 asyncio.run 包裹（项目现有模式，无 pytest-asyncio 依赖）。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.features.agent import agent_loop
from app.models.material import Material
from app.models.user import User
from app.features.materials import extraction_service, service as material_service
from app.features.materials.markdown_extraction_service import MarkdownExtractionResult
from app.utils.security import hash_password


def _student(db: Session, name: str) -> User:
    user = User(
        username=f"ingest_{uuid4().hex[:10]}",
        password_hash=hash_password("x"),
        role="student",
        display_name=name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_image(tmp_path, name: str = "words.png") -> str:
    upload_root = tmp_path / "uploads"
    (upload_root / "materials").mkdir(parents=True, exist_ok=True)
    image_path = upload_root / "materials" / name
    image_path.write_bytes(b"fake-image-bytes")
    return str(upload_root.parent)


def _result(markdown="### 单词表\napple 苹果", confidence="high", uncertain=None, provider="mimo"):
    return MarkdownExtractionResult(
        markdown=markdown,
        raw_text=markdown,
        confidence=confidence,
        uncertain_points=uncertain or [],
        content_type="英语单词表",
        provider=provider,
        elapsed_ms=120,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() else asyncio.run(coro)


# ---- ensure_extraction 幂等 ----


def test_ensure_extraction_skips_already_recognized(db: Session, tmp_path, monkeypatch):
    student = _student(db, "幂等学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="已识别",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        recognized_markdown="### 旧内容",
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(return_value=_result("### 不应被调用"))
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=False))

    recognize_mock.assert_not_awaited()
    db.refresh(material)
    assert material.recognized_markdown == "### 旧内容"


def test_ensure_extraction_processing_returns_current(db: Session, tmp_path, monkeypatch):
    student = _student(db, "进行中学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="识别中",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="processing",
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock()
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=False))

    recognize_mock.assert_not_awaited()
    db.refresh(material)
    assert material.recognition_status == "processing"


def test_ensure_extraction_force_re_recognizes_but_keeps_confirmed(db: Session, tmp_path, monkeypatch):
    student = _student(db, "强制重识别学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="强制重识别",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        recognized_markdown="### 旧识别稿",
        confirmed_markdown="### 已确认稿",
        confirmed_at=datetime.now(),
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(return_value=_result("### 新识别稿\nbanana 香蕉", confidence="high"))
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    recognize_mock.assert_awaited_once()
    db.refresh(material)
    assert material.recognized_markdown == "### 新识别稿\nbanana 香蕉"
    # force 重识别保留 confirmed（spec 7.2 / 6.1）
    assert material.confirmed_markdown == "### 已确认稿"
    assert material.confirmed_at is not None


# ---- auto_ready 状态流转 ----


def test_high_confidence_non_empty_sets_auto_ready(db: Session, tmp_path, monkeypatch):
    student = _student(db, "高置信学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="高置信",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(return_value=_result("### 单词表\napple 苹果", confidence="high"))
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    db.refresh(material)
    assert material.recognition_status == "recognized"
    assert material.auto_ready is True
    assert material.recognition_confidence == "high"
    assert material.recognition_provider == "mimo"
    assert material.content_fingerprint  # 识别成功后写了指纹


def test_low_confidence_not_auto_ready_needs_review(db: Session, tmp_path, monkeypatch):
    student = _student(db, "低置信学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="低置信",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(
        return_value=_result("### 模糊内容\napple [?]", confidence="low", uncertain=["apple 拼写不确定"])
    )
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    db.refresh(material)
    assert material.recognition_status == "needs_review"
    assert material.auto_ready is False
    assert material.recognition_confidence == "low"
    assert material.uncertain_points == ["apple 拼写不确定"]  # 保留了 provider/confidence/uncertain


def test_high_confidence_with_uncertain_points_not_auto_ready(db: Session, tmp_path, monkeypatch):
    """高置信但有 uncertain_points -> 不自动可用（spec 6.4）。"""
    student = _student(db, "有不确定点学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="有不确定",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(
        return_value=_result("### 内容\napple 苹果", confidence="high", uncertain=["apple 拼写不确定"])
    )
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    db.refresh(material)
    assert material.recognition_status == "needs_review"
    assert material.auto_ready is False


def test_empty_recognition_marks_failed_and_no_auto_ready(db: Session, tmp_path, monkeypatch):
    """LLM 返回空内容 -> status=failed，recognized_markdown 保持空，不进 Agent。"""
    student = _student(db, "空内容学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="空内容",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(return_value=_result("", confidence="low"))
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    db.refresh(material)
    assert material.recognition_status == "failed"
    assert material.auto_ready is False
    assert (material.recognized_markdown or "").strip() == ""
    assert not material.content_fingerprint  # 空内容不写指纹


def test_recognition_failure_marks_failed(db: Session, tmp_path, monkeypatch):
    """识别异常 -> status=failed，auto_ready=0，不阻断（ensure_extraction 自身不抛，返回 failed 状态）。"""
    student = _student(db, "失败学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="识别失败",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    recognize_mock = AsyncMock(side_effect=RuntimeError("OCR timeout"))
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    db.refresh(material)
    assert material.recognition_status == "failed"
    assert material.auto_ready is False


# ---- 上传不触发识别（懒触发） ----


def test_upload_does_not_trigger_recognition(db: Session, tmp_path, monkeypatch):
    """upload_material_async 只做去重+上传+落库，不调识别；状态保持 pending，识别懒到首次 read_material。"""
    student = _student(db, "懒触发学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))

    recognize_mock = AsyncMock(return_value=_result("### 不应被调用", confidence="high"))
    with patch.object(material_service, "upload_file", return_value="local:materials/words.png"), patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock
    ):
        resp = asyncio.run(
            material_service.upload_material_async(db, b"fake-image", "png", "懒识别", "image", [], student)
        )

    recognize_mock.assert_not_awaited()
    record = db.get(Material, resp.material_id)
    assert record is not None
    assert record.recognition_status == "pending"
    assert record.auto_ready is False


def test_upload_unaffected_by_recognition_failure(db: Session, tmp_path, monkeypatch):
    """上传与识别解耦：识别会抛错也不影响上传落库，状态保持 pending（识别懒触发，失败由 read_material 处理）。"""
    student = _student(db, "不阻断学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))

    recognize_mock = AsyncMock(side_effect=RuntimeError("OCR down"))
    with patch.object(material_service, "upload_file", return_value="local:materials/words.png"), patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock
    ):
        resp = asyncio.run(
            material_service.upload_material_async(db, b"fake-image", "png", "失败也上传", "image", [], student)
        )

    recognize_mock.assert_not_awaited()  # 上传不调识别，故其失败无从影响上传
    assert resp.is_duplicate is False
    record = db.get(Material, resp.material_id)
    assert record is not None
    assert record.recognition_status == "pending"
    assert record.auto_ready is False


# ---- 内容指纹归一 ----


def test_content_fingerprint_hit_sets_duplicate_of(db: Session, tmp_path, monkeypatch):
    """两份不同文件识别出相同内容 -> 第二份 duplicate_of 指向第一份，列表只显第一份。"""
    student = _student(db, "归一学生")
    upload_root = tmp_path / "uploads"
    (upload_root / "materials").mkdir(parents=True, exist_ok=True)
    (upload_root / "materials" / "a.png").write_bytes(b"a-bytes")
    (upload_root / "materials" / "b.png").write_bytes(b"b-bytes")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    same_markdown = "### 单词表\napple 苹果\nbanana 香蕉"
    # 尾注措辞不同，正文相同 -> 同指纹
    result_a = _result(
        same_markdown + "\n识别置信度：90%\n需要人工确认的内容：无\n适合作为哪类学习素材：英语单词表",
        confidence="high",
    )
    result_b = _result(
        same_markdown + "\n识别置信度：92%\n需要人工确认的内容：暂无\n适合作为哪类学习素材：英语单词表，可背诵",
        confidence="high",
    )

    m1 = Material(
        name="第一份",
        type="image",
        source="student",
        content_ref="local:materials/a.png",
        uploaded_by=student.id,
        student_id=student.id,
        file_sha256="a-hash",
    )
    m2 = Material(
        name="第二份",
        type="image",
        source="student",
        content_ref="local:materials/b.png",
        uploaded_by=student.id,
        student_id=student.id,
        file_sha256="b-hash",
    )
    db.add_all([m1, m2])
    db.commit()
    db.refresh(m1)
    db.refresh(m2)

    recognize_results = AsyncMock(side_effect=[result_a, result_b])
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_results):
        asyncio.run(extraction_service.ensure_extraction(db, m1.id, student, force=True))
        asyncio.run(extraction_service.ensure_extraction(db, m2.id, student, force=True))

    db.refresh(m1)
    db.refresh(m2)
    assert m1.content_fingerprint == m2.content_fingerprint
    assert m1.duplicate_of_material_id is None  # 规范素材
    assert m2.duplicate_of_material_id == m1.id  # 归一到第一份
    # 两份记录都保留
    assert db.query(Material).filter(Material.uploaded_by == student.id).count() == 2


def test_list_materials_excludes_duplicates_by_default(db: Session):
    """list_materials 默认排除 duplicate_of 非空的素材（归一展示）。"""
    student = _student(db, "列表归一学生")
    canonical = Material(
        name="规范素材",
        type="image",
        source="student",
        content_ref="local:materials/c.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        duplicate_of_material_id=None,
    )
    duplicate = Material(
        name="重复素材",
        type="image",
        source="student",
        content_ref="local:materials/d.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        duplicate_of_material_id=None,  # 先建
    )
    db.add_all([canonical, duplicate])
    db.commit()
    db.refresh(canonical)
    db.refresh(duplicate)
    duplicate.duplicate_of_material_id = canonical.id
    db.commit()

    items = material_service.list_materials(db, student)
    names = [i.name for i in items]
    assert "规范素材" in names
    assert "重复素材" not in names


def test_list_materials_include_duplicates_shows_all(db: Session):
    """include_duplicates=True 显示全部。"""
    student = _student(db, "包含重复学生")
    canonical = Material(
        name="规范2",
        type="image",
        source="student",
        content_ref="local:materials/c2.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
    )
    duplicate = Material(
        name="重复2",
        type="image",
        source="student",
        content_ref="local:materials/d2.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
    )
    db.add_all([canonical, duplicate])
    db.commit()
    db.refresh(canonical)
    db.refresh(duplicate)
    duplicate.duplicate_of_material_id = canonical.id
    db.commit()

    items = material_service.list_materials(db, student, include_duplicates=True)
    names = [i.name for i in items]
    assert "规范2" in names
    assert "重复2" in names


# ---- read_material 归一与 auto_ready 分支 ----


def test_read_material_normalizes_to_canonical(db: Session, tmp_path, monkeypatch):
    """read_material 读取 duplicate 素材 -> 归一到规范素材内容。"""
    student = _student(db, "读取归一学生")
    canonical = Material(
        name="规范素材读取",
        type="image",
        source="student",
        content_ref="local:materials/canon.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        recognized_markdown="### 规范内容\napple 苹果",
        auto_ready=True,
    )
    duplicate = Material(
        name="重复素材读取",
        type="image",
        source="student",
        content_ref="local:materials/dup.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        recognized_markdown="### 原始重复内容",
    )
    db.add_all([canonical, duplicate])
    db.commit()
    db.refresh(canonical)
    db.refresh(duplicate)
    duplicate.duplicate_of_material_id = canonical.id
    db.commit()

    result = asyncio.run(
        agent_loop._handle_read_material({"material_id": duplicate.id}, "student", db, student.id)
    )
    assert "error" not in result
    assert "规范内容" in result.get("content", "")
    assert result.get("content_source") == "auto_ready_markdown"


def test_read_material_auto_ready_no_confirmation_needed(db: Session, tmp_path, monkeypatch):
    """auto_ready=True -> needs_confirmation=False，content_source=auto_ready_markdown。"""
    student = _student(db, "auto_ready 读取学生")
    material = Material(
        name="自动可用素材",
        type="image",
        source="student",
        content_ref="local:materials/ar.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="recognized",
        recognized_markdown="### 自动可用\napple 苹果",
        auto_ready=True,
    )
    db.add(material)
    db.commit()

    result = asyncio.run(
        agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
    )
    assert result["content_source"] == "auto_ready_markdown"
    assert result["needs_confirmation"] is False
    assert "fallback_hint" not in result


def test_read_material_failed_does_not_inject_content(db: Session, tmp_path, monkeypatch):
    """failed 素材 recognized_markdown 空 -> 不进 Agent 上下文（落到 fallback）。"""
    student = _student(db, "失败读取学生")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", _make_image(tmp_path))
    material = Material(
        name="失败素材读取",
        type="image",
        source="student",
        content_ref="local:materials/words.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="failed",
        recognized_markdown=None,
        auto_ready=False,
    )
    db.add(material)
    db.commit()

    # 失败素材 recognized_markdown 为空，落到 fallback 视觉分支；mock 视觉也失败 -> 返回 fallback_hint
    with patch("app.features.agent.agent_loop.ai_service.call_llm", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = asyncio.run(
            agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
        )
    # 不应把空内容当成功注入；应有 fallback_hint 或 error，content 不应是空串成功的样子
    assert result.get("content") in (None, "") or "fallback_hint" in result or "error" in result


# ---- 近似内容只提示 ----


def test_similar_but_not_identical_content_does_not_set_duplicate_of(db: Session, tmp_path, monkeypatch):
    """两份相似但不完全相同的正文 -> 内容指纹不同 -> 不设 duplicate_of（近似留 TODO，本 PR 不做）。"""
    student = _student(db, "近似学生")
    upload_root = tmp_path / "uploads"
    (upload_root / "materials").mkdir(parents=True, exist_ok=True)
    (upload_root / "materials" / "sa.png").write_bytes(b"a-bytes")
    (upload_root / "materials" / "sb.png").write_bytes(b"b-bytes")
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(upload_root.parent))

    result_a = _result("### 单词表\napple 苹果\nbanana 香蕉", confidence="high")
    result_b = _result("### 单词表\napple 苹果\nbanana 香蕉\norange 橘子", confidence="high")

    m1 = Material(
        name="近似1",
        type="image",
        source="student",
        content_ref="local:materials/sa.png",
        uploaded_by=student.id,
        student_id=student.id,
        file_sha256="sa-hash",
    )
    m2 = Material(
        name="近似2",
        type="image",
        source="student",
        content_ref="local:materials/sb.png",
        uploaded_by=student.id,
        student_id=student.id,
        file_sha256="sb-hash",
    )
    db.add_all([m1, m2])
    db.commit()
    db.refresh(m1)
    db.refresh(m2)

    recognize_results = AsyncMock(side_effect=[result_a, result_b])
    with patch("app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_results):
        asyncio.run(extraction_service.ensure_extraction(db, m1.id, student, force=True))
        asyncio.run(extraction_service.ensure_extraction(db, m2.id, student, force=True))

    db.refresh(m1)
    db.refresh(m2)
    assert m1.content_fingerprint != m2.content_fingerprint
    assert m1.duplicate_of_material_id is None
    assert m2.duplicate_of_material_id is None  # 近似不归一


# ---- confirmed 优先级不变 ----


def test_confirmed_markdown_priority_over_auto_ready(db: Session, tmp_path, monkeypatch):
    """有 confirmed_markdown 时优先用 confirmed（即使 auto_ready=True）。"""
    student = _student(db, "确认优先学生")
    material = Material(
        name="已确认素材",
        type="image",
        source="student",
        content_ref="local:materials/conf.png",
        uploaded_by=student.id,
        student_id=student.id,
        recognition_status="confirmed",
        recognized_markdown="### 机器识别稿",
        confirmed_markdown="### 人工确认稿\napple 苹果",
        auto_ready=True,
    )
    db.add(material)
    db.commit()

    result = asyncio.run(
        agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
    )
    assert result["content_source"] == "confirmed_markdown"
    assert result["needs_confirmation"] is False
    assert "人工确认稿" in result["content"]


# ---- COS 临时下载识别 ----


def test_cos_material_download_and_recognize(db: Session, tmp_path, monkeypatch):
    """COS 存储素材（无 local: 前缀）-> download_to_temp 下载临时文件 -> 识别 -> 清理。"""
    from app.config import settings

    monkeypatch.setattr(settings, "COS_SECRET_ID", "fake-id")
    monkeypatch.setattr(settings, "COS_BUCKET", "fake-bucket")

    student = _student(db, "COS 学生")
    temp_file = tmp_path / "downloaded.png"
    temp_file.write_bytes(b"downloaded-image")

    material = Material(
        name="COS 素材",
        type="image",
        source="student",
        content_ref="materials/2026/07/cos.png",  # 无 local: 前缀
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()

    download_mock = AsyncMock(return_value=str(temp_file))
    recognize_mock = AsyncMock(return_value=_result("### COS 内容\napple 苹果", confidence="high"))
    with patch("app.utils.cos.download_to_temp", new=download_mock), patch(
        "app.features.materials.markdown_extraction_service.recognize_images_to_markdown", new=recognize_mock
    ):
        asyncio.run(extraction_service.ensure_extraction(db, material.id, student, force=True))

    download_mock.assert_awaited_once()
    recognize_mock.assert_awaited_once()
    db.refresh(material)
    assert material.recognition_status == "recognized"
    assert material.auto_ready is True
    assert "COS 内容" in (material.recognized_markdown or "")
