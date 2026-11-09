"""素材懒识别：上传不识别，首次 read_material 触发识别并缓存，后续读缓存。

覆盖：
- upload_material_async 不再触发识别，状态留 pending。
- read_material 首次调用触发 ensure_extraction 写缓存；二次调用走缓存（不重复调视觉）。
- txt/md 素材直读正文写缓存，不走视觉。
"""

import asyncio
from unittest.mock import AsyncMock, patch

from app.features.agent import agent_loop
from app.models.material import Material
from app.models.user import User
from app.features.materials import extraction_service, markdown_extraction_service
from app.features.materials import service as material_service
from app.features.materials.markdown_extraction_service import MarkdownExtractionResult


def test_upload_does_not_trigger_recognition(db, monkeypatch):
    """上传只落库+去重，状态留 pending，不调识别。"""
    student = db.get(User, 2)

    async def fake_recognize(*_args, **_kw):
        raise AssertionError("上传不应触发识别")

    monkeypatch.setattr(markdown_extraction_service, "recognize_images_to_markdown", fake_recognize)
    monkeypatch.setattr(material_service, "upload_file", lambda _b, _e: "materials/fake.png")

    resp = asyncio.run(
        material_service.upload_material_async(
            db, b"fakepng", "png", "懒识别图", "image", [], student
        )
    )
    material = db.get(Material, resp.material_id)
    assert material.recognition_status == "pending"
    assert material.recognized_markdown is None


def test_read_material_lazy_recognizes_and_caches(db, tmp_path, monkeypatch):
    """read_material 首次触发识别并写缓存，二次走缓存不重复调视觉。"""
    student = db.get(User, 2)
    image_path = tmp_path / "lazy.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG 魔数过扩展名校验

    extraction_result = MarkdownExtractionResult(
        markdown="### 单词表\n\napple 苹果",
        confidence="high",
        content_type="word_list",
        provider="mock",
    )
    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(image_path))

    material = Material(
        name="懒识别图",
        type="image",
        source="student",
        content_ref="local:materials/lazy.png",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    assert material.recognition_status == "pending"

    with patch.object(
        markdown_extraction_service,
        "recognize_images_to_markdown",
        new_callable=AsyncMock,
        return_value=extraction_result,
    ) as mock_recognize:
        # 首次读取：触发识别
        first = asyncio.run(
            agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
        )
        assert "apple 苹果" in first["content"]
        assert mock_recognize.await_count == 1

        db.refresh(material)
        assert material.recognition_status == "recognized"
        assert material.auto_ready is True
        assert (material.recognized_markdown or "").strip()

        # 二次读取：走缓存，不再调视觉
        second = asyncio.run(
            agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
        )
        assert "apple 苹果" in second["content"]
        assert mock_recognize.await_count == 1  # 没有第二次调用


def test_read_material_text_direct_for_txt(db, tmp_path, monkeypatch):
    """txt 素材直读正文写缓存，不走视觉。"""
    student = db.get(User, 2)
    text_path = tmp_path / "words.txt"
    text_path.write_text("apple 苹果\nbanana 香蕉", encoding="utf-8")

    async def fail_recognize(*_args, **_kw):
        raise AssertionError("txt/md 不应走视觉识别")

    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(text_path))
    monkeypatch.setattr(markdown_extraction_service, "recognize_images_to_markdown", fail_recognize)

    material = Material(
        name="单词txt",
        type="doc",
        source="student",
        content_ref="local:materials/words.txt",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    assert material.recognition_status == "pending"

    result = asyncio.run(
        agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
    )
    assert "apple 苹果" in result["content"]
    assert "banana 香蕉" in result["content"]

    db.refresh(material)
    assert material.recognition_status == "recognized"
    assert material.recognition_provider == "text_direct"


def test_read_material_retries_failed_cos_material(db, tmp_path, monkeypatch):
    """failed 状态的 COS 素材在 read_material 时自动重试识别并恢复。

    回归 COS 下载契约修复：旧代码 download_to_temp 误用 response["raw_stream"]
    抛 KeyError 导致素材 failed；修复后 failed 素材下次读取会重新下载识别，
    无需重新上传或迁移 COS 文件。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "COS_SECRET_ID", "fake-id")
    monkeypatch.setattr(settings, "COS_BUCKET", "fake-bucket")

    student = db.get(User, 2)
    image_path = tmp_path / "cos_material.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG 魔数

    extraction_result = MarkdownExtractionResult(
        markdown="### 单词表\n\napple 苹果\nbanana 香蕉",
        confidence="high",
        content_type="word_list",
        provider="mock",
    )

    download_mock = AsyncMock(return_value=str(image_path))
    material = Material(
        name="失败的 COS 素材",
        type="image",
        source="student",
        content_ref="materials/2026/07/cos-failed.png",  # 无 local: 前缀 = COS 存储
        recognition_status="failed",  # 之前因 COS 下载 bug 失败
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    assert material.recognition_status == "failed"

    with patch("app.utils.cos.download_to_temp", new=download_mock), patch.object(
        markdown_extraction_service,
        "recognize_images_to_markdown",
        new_callable=AsyncMock,
        return_value=extraction_result,
    ) as recognize_mock:
        result = asyncio.run(
            agent_loop._handle_read_material({"material_id": material.id}, "student", db, student.id)
        )

    assert "apple 苹果" in result["content"]
    assert result["content_source"] == "auto_ready_markdown"

    db.refresh(material)
    assert material.recognition_status == "recognized"
    assert material.auto_ready is True
    assert (material.recognized_markdown or "").strip()
    download_mock.assert_awaited_once()
    recognize_mock.assert_awaited_once()
