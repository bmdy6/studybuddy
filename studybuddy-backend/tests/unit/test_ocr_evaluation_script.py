import importlib.util
from pathlib import Path


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "evaluate_question_bank_ocr.py"
    spec = importlib.util.spec_from_file_location("evaluate_question_bank_ocr", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluate_extracted_text_counts_questions_and_answers():
    module = _load_script_module()
    text = "1. He ___ to school. A. go B. went 答案：B 2. 计算 2+3。答案：5"

    result = module.evaluate_extracted_text(text, expected_question_count=2)

    assert result["parsed_question_count"] == 2
    assert result["answer_count"] == 2
    assert result["answer_coverage_rate"] == 1
    assert result["question_recall_rate"] == 1


def test_evaluate_pdf_uses_mock_ocr_for_textless_pdf(tmp_path):
    import asyncio

    import fitz

    module = _load_script_module()
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "blank-scan.pdf"
    doc.save(pdf_path)
    doc.close()

    result = asyncio.run(
        module.evaluate_pdf(
            pdf_path,
            expected_question_count=1,
            mock_ocr_text="1. 计算 2+3。答案：5",
        )
    )

    assert result["used_vision_ocr"] is True
    assert result["parsed_question_count"] == 1
    assert result["question_recall_rate"] == 1
    assert result["warnings"] == ["PDF 未抽取到文本，使用 mock OCR 文本评估"]


def test_evaluate_pdf_passes_vision_max_pages(tmp_path, monkeypatch):
    import asyncio

    import fitz

    module = _load_script_module()
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "blank-scan.pdf"
    doc.save(pdf_path)
    doc.close()

    seen: dict[str, int] = {}

    async def _fake_vision_ocr(data: bytes, max_pages: int = 3, start_page: int = 0, page_zoom: float = 2.0) -> str:
        seen["max_pages"] = max_pages
        seen["start_page"] = start_page
        seen["page_zoom"] = int(page_zoom)
        return "1. 计算 2+3。答案：5"

    monkeypatch.setattr(module.question_bank_service, "_extract_scanned_pdf_text_with_vision", _fake_vision_ocr)

    result = asyncio.run(module.evaluate_pdf(pdf_path, expected_question_count=1, use_vision=True, vision_max_pages=6))

    assert seen["max_pages"] == 6
    assert seen["start_page"] == 0
    assert seen["page_zoom"] == 2
    assert result["used_vision_ocr"] is True
    assert result["parsed_question_count"] == 1
    assert result["warnings"] == ["PDF 未抽取到文本，已调用视觉/OCR 评估前 6 页（batch_pages=6, zoom=2.0）"]


def test_evaluate_pdf_can_batch_vision_pages(tmp_path, monkeypatch):
    import asyncio

    import fitz

    module = _load_script_module()
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_path = tmp_path / "blank-scan.pdf"
    doc.save(pdf_path)
    doc.close()

    starts: list[int] = []

    async def _fake_vision_ocr(data: bytes, max_pages: int = 3, start_page: int = 0, page_zoom: float = 2.0) -> str:
        starts.append(start_page)
        return f"{start_page + 1}. 计算 2+3。答案：5"

    monkeypatch.setattr(module.question_bank_service, "_extract_scanned_pdf_text_with_vision", _fake_vision_ocr)

    result = asyncio.run(
        module.evaluate_pdf(
            pdf_path,
            expected_question_count=2,
            use_vision=True,
            vision_max_pages=2,
            vision_batch_pages=1,
            vision_page_zoom=1.0,
        )
    )

    assert starts == [0, 1]
    assert result["vision_batch_count"] == 2
    assert result["successful_vision_batches"] == 2
    assert result["parsed_question_count"] == 2
