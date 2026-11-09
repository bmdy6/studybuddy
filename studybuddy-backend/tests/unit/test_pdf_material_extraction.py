"""素材 PDF 识别分支：pdf_service 成功 / 降级（扫描型或失败）两路径。"""

import asyncio
from unittest.mock import patch

import pytest

from app.core.pdf_service import PdfExtractionResult
from app.features.materials import extraction_service
from app.models.material import Material
from app.models.user import User


def _make_pdf_material(db, tmp_path, name="pdf素材.pdf"):
    student = db.get(User, 2)
    pdf_path = tmp_path / name
    pdf_path.write_bytes(b"%PDF-1.4 fake minimal pdf")
    material = Material(
        name="PDF素材",
        type="pdf",
        source="student",
        content_ref=f"local:materials/{name}",
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material, pdf_path


def test_pdf_text_based_recognition_success(db, tmp_path, monkeypatch):
    """文本型 PDF -> 识别成功：recognized_markdown 有内容、provider=pdf_inspector、状态终态。"""
    material, pdf_path = _make_pdf_material(db, tmp_path)
    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(pdf_path))

    with patch("app.core.pdf_service.extract_pdf_markdown") as mock_extract:
        mock_extract.return_value = PdfExtractionResult(
            pdf_type="text_based",
            markdown="# 一元一次方程单元测试\n\n1. 解方程：2x + 3 = 7\n",
            has_encoding_issues=False,
            elapsed_ms=7,
        )
        resp = asyncio.run(extraction_service.ensure_extraction(db, material.id, db.get(User, 2)))

    assert resp.recognition_status in {"recognized", "needs_review"}
    assert resp.recognition_provider == "pdf_inspector"
    assert "一元一次方程单元测试" in resp.recognized_markdown
    assert mock_extract.call_count == 1


def test_pdf_scanned_returns_precondition_error(db, tmp_path, monkeypatch):
    """扫描/图像型 PDF（extract_pdf_markdown 返回 None）-> 抛前置条件错误，状态回滚 pending，不置 failed。"""
    material, pdf_path = _make_pdf_material(db, tmp_path)
    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(pdf_path))

    with patch("app.core.pdf_service.extract_pdf_markdown") as mock_extract:
        mock_extract.return_value = None  # 扫描型/解析失败 -> 降级
        with pytest.raises(extraction_service.MaterialRecognitionPreconditionError):
            asyncio.run(extraction_service.ensure_extraction(db, material.id, db.get(User, 2)))

    db.refresh(material)
    assert material.recognition_status == "pending"  # 保留原语义，不进 failed
    assert material.recognized_markdown is None


def test_pdf_empty_markdown_returns_precondition_error(db, tmp_path, monkeypatch):
    """提取结果 markdown 为空 -> 与 None 同语义，抛前置条件错误。"""
    material, pdf_path = _make_pdf_material(db, tmp_path)
    monkeypatch.setattr(extraction_service, "_resolve_recognition_input_path", lambda _m: str(pdf_path))

    with patch("app.core.pdf_service.extract_pdf_markdown") as mock_extract:
        mock_extract.return_value = PdfExtractionResult(
            pdf_type="text_based", markdown="   \n", has_encoding_issues=False, elapsed_ms=5
        )
        with pytest.raises(extraction_service.MaterialRecognitionPreconditionError):
            asyncio.run(extraction_service.ensure_extraction(db, material.id, db.get(User, 2)))

    db.refresh(material)
    assert material.recognition_status == "pending"
