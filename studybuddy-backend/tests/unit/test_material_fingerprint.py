"""素材内容指纹规范化单测（纯函数，无 DB 依赖）。

覆盖 spec 第七章：尾注三行不参与指纹、换行/空行/首尾空白归一、
相同正文不同尾注应得到相同 fingerprint。
"""

import hashlib

from app.features.materials.extraction_service import _normalize_markdown_for_fingerprint


def _fingerprint(markdown: str) -> str:
    return hashlib.sha256(_normalize_markdown_for_fingerprint(markdown).encode("utf-8")).hexdigest()


def test_normalize_strips_leading_trailing_whitespace_and_unifies_newlines():
    normalized = _normalize_markdown_for_fingerprint("  ### 单词表\n\napple 苹果  \n\n  ")
    # 段落间单个空行保留（spec：连续空行合并为一个，去尾部空行）
    assert normalized == "### 单词表\n\napple 苹果"


def test_normalize_collapses_consecutive_blank_lines():
    one_blank = _normalize_markdown_for_fingerprint("a\n\nb")
    many_blanks = _normalize_markdown_for_fingerprint("a\n\n\n\n\nb")
    assert _fingerprint(one_blank) == _fingerprint(many_blanks)


def test_normalize_strips_per_line_whitespace():
    with_indent = _normalize_markdown_for_fingerprint("  a\n\t b\n  c")
    no_indent = _normalize_markdown_for_fingerprint("a\nb\nc")
    assert _fingerprint(with_indent) == _fingerprint(no_indent)


def test_fingerprint_ignores_recognition_footer_three_lines():
    """LLM 尾注三行措辞会微变，正文相同即应判为内容重复。"""
    body = "### 单词表\napple 苹果\nbanana 香蕉"
    version_a = (
        body
        + "\n识别置信度：90%\n需要人工确认的内容：无\n适合作为哪类学习素材：英语单词表"
    )
    version_b = (
        body
        + "\n识别置信度：92%\n需要人工确认的内容：暂无\n适合作为哪类学习素材：英语单词表，可作为背诵素材"
    )
    assert _fingerprint(version_a) == _fingerprint(version_b)


def test_fingerprint_differs_for_different_body():
    a = _fingerprint("### 单词表\napple 苹果")
    b = _fingerprint("### 单词表\nbanana 香蕉")
    assert a != b


def test_normalize_handles_empty_and_whitespace_only():
    assert _normalize_markdown_for_fingerprint("") == ""
    assert _normalize_markdown_for_fingerprint("   \n\n  \n") == ""


def test_normalize_keeps_blank_line_between_paragraphs_as_single_separator():
    normalized = _normalize_markdown_for_fingerprint("第一段\n\n\n第二段")
    assert normalized == "第一段\n\n第二段"
