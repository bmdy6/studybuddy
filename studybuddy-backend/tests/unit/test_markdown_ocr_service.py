"""图片转 Markdown 外部 OCR provider 单测。"""

import sys

from app.features.materials import markdown_ocr_service


def test_external_cli_provider_returns_markdown(tmp_path, monkeypatch):
    """配置外部 OCR CLI 后，应读取 stdout 作为 Markdown 识别稿。"""
    photo = tmp_path / "homework.png"
    photo.write_bytes(b"fake image")
    cli = tmp_path / "ocr_cli.py"
    cli.write_text(
        "import sys\n"
        "print('### OCR识别稿')\n"
        "print('图片路径：' + sys.argv[1])\n"
        "print('学生作答：[?]')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_PROVIDER", "external_cli")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_COMMAND", f"{sys.executable} {cli} {{photo}}")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_TIMEOUT_SEC", 5)

    result = markdown_ocr_service.recognize_photos_to_markdown([str(photo)])

    assert result is not None
    assert result.provider == "external_cli"
    assert "OCR识别稿" in result.markdown
    assert str(photo) in result.markdown
    assert result.warnings == []


def test_external_cli_provider_timeout_returns_none(tmp_path, monkeypatch):
    """外部 OCR 超时不能拖垮拍题链路，应返回 None 让上层回退到视觉模型。"""
    photo = tmp_path / "homework.png"
    photo.write_bytes(b"fake image")
    cli = tmp_path / "slow_ocr.py"
    cli.write_text("import time\ntime.sleep(5)\nprint('too late')\n", encoding="utf-8")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_PROVIDER", "external_cli")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_COMMAND", f"{sys.executable} {cli} {{photo}}")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_TIMEOUT_SEC", 1)

    result = markdown_ocr_service.recognize_photos_to_markdown([str(photo)])

    assert result is None


def test_disabled_provider_returns_none(tmp_path, monkeypatch):
    """默认 provider 关闭外部 OCR，生产继续走现有 MiMo 视觉路径。"""
    photo = tmp_path / "homework.png"
    photo.write_bytes(b"fake image")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_PROVIDER", "mimo")
    monkeypatch.setattr(markdown_ocr_service.settings, "MARKDOWN_OCR_COMMAND", "")

    result = markdown_ocr_service.recognize_photos_to_markdown([str(photo)])

    assert result is None
