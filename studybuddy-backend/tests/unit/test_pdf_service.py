"""pdf_service 单测：分类、提取、异常降级、未装库降级。"""

import os
import sys
from unittest.mock import patch

import pymupdf
import pytest

from app.core import pdf_service


def _make_text_pdf(path: str, lines: list[str]) -> None:
    """用 pymupdf 生成最小文本型 PDF（英文，内置字体）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 30), line, fontsize=12)
    doc.save(path)
    doc.close()


def _make_cn_text_pdf(path: str, lines: list[str]) -> None:
    """生成含中文的文本型 PDF；找不到中文字体时跳过（依赖系统字体）。"""
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    font_path = next((p for p in font_candidates if os.path.exists(p)), None)
    if font_path is None:
        pytest.skip("未找到系统中文字体，跳过中文 PDF 用例")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="cn", fontfile=font_path)
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 30), line, fontname="cn", fontsize=14)
    doc.save(path)
    doc.close()


def _make_image_pdf(path: str) -> None:
    """生成纯图片型 PDF：先画一页无文本层的页，再转存。"""
    doc = pymupdf.open()
    page = doc.new_page()
    # 画一个纯图形（无文本层），模拟扫描件
    page.draw_rect(pymupdf.Rect(72, 100, 300, 300), color=(0, 0, 0))
    doc.save(path)
    doc.close()


def test_extract_text_pdf_returns_markdown(tmp_path):
    """文本型 PDF -> text_based + 非空 markdown。"""
    pdf = tmp_path / "text.pdf"
    _make_text_pdf(str(pdf), ["Math Quiz", "Solve 2x + 3 = 7", "Answer: x = 2"])

    result = pdf_service.extract_pdf_markdown(str(pdf))

    assert result is not None
    assert result.pdf_type == "text_based"
    assert "2x + 3 = 7" in result.markdown
    assert result.elapsed_ms >= 0


def test_extract_cn_pdf_returns_correct_markdown(tmp_path):
    """中文文本型 PDF -> 中文提取正确。"""
    pdf = tmp_path / "cn.pdf"
    _make_cn_text_pdf(str(pdf), ["一元一次方程单元测试", "1. 解方程：2x + 3 = 7", "答案：x = 2"])

    result = pdf_service.extract_pdf_markdown(str(pdf))

    assert result is not None
    assert result.pdf_type == "text_based"
    assert "一元一次方程单元测试" in result.markdown
    assert "2x + 3 = 7" in result.markdown


def test_extract_missing_file_returns_none(tmp_path):
    """不存在的文件 -> 返回 None，不抛异常。"""
    result = pdf_service.extract_pdf_markdown(str(tmp_path / "missing.pdf"))
    assert result is None


def test_extract_corrupt_file_returns_none(tmp_path):
    """损坏 PDF -> 返回 None，不抛异常。"""
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"this is not a pdf at all" * 100)

    result = pdf_service.extract_pdf_markdown(str(pdf))
    assert result is None


def test_extract_image_pdf_returns_none_or_scanned(tmp_path):
    """纯图片（无文本层）PDF -> 返回 None 或 pdf_type 标记 scanned，不抛异常。"""
    pdf = tmp_path / "image.pdf"
    _make_image_pdf(str(pdf))

    result = pdf_service.extract_pdf_markdown(str(pdf))

    if result is None:
        return  # 上层按"需 OCR"降级，语义正确
    assert result.pdf_type in {"scanned", "image_based", "mixed"}


def test_classify_text_pdf(tmp_path):
    """classify_pdf 返回分类结果。"""
    pdf = tmp_path / "text.pdf"
    _make_text_pdf(str(pdf), ["Hello"])

    result = pdf_service.classify_pdf(str(pdf))

    assert result is not None
    assert result.pdf_type == "text_based"


def test_uninstalled_library_degrades_gracefully(tmp_path):
    """未装 pdf-inspector 时 -> 优雅降级返回 None，不抛异常。"""
    pdf = tmp_path / "text.pdf"
    _make_text_pdf(str(pdf), ["Hello"])

    with patch.dict(sys.modules, {"pdf_inspector": None}):
        # import 语句会因 sys.modules 里是 None 抛 ImportError，模拟未装库
        assert pdf_service.extract_pdf_markdown(str(pdf)) is None
        assert pdf_service.classify_pdf(str(pdf)) is None
