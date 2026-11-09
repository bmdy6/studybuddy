"""评估题库 PDF/OCR 抽题效果。

用法：
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_ocr.py /path/to/paper.pdf --expected-question-count 50
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_ocr.py /path/to/scanned.pdf --use-vision
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_ocr.py /path/to/scanned.pdf --use-vision --vision-max-pages 6 --vision-batch-pages 1
  PYTHONPATH=. .venv/bin/python scripts/evaluate_question_bank_ocr.py /path/to/scanned.pdf --mock-ocr-text-file ocr.txt

默认不调用视觉模型；只有传入 --use-vision 才会走 MiMo 视觉 OCR。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.features.question_bank import service as question_bank_service


def _safe_rate(numerator: int, denominator: int | None) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def evaluate_extracted_text(text: str, expected_question_count: int | None = None) -> dict[str, Any]:
    drafts = question_bank_service._parse_questions_from_text(text)
    parsed_count = len(drafts)
    answer_count = sum(1 for draft in drafts if draft.get("answer"))
    question_recall = _safe_rate(parsed_count, expected_question_count)
    return {
        "text_length": len(text),
        "parsed_question_count": parsed_count,
        "answer_count": answer_count,
        "answer_coverage_rate": _safe_rate(answer_count, parsed_count),
        "expected_question_count": expected_question_count,
        "question_recall_rate": question_recall,
        "sample_questions": [
            {
                "question_no": draft.get("question_no"),
                "stem": str(draft.get("stem", ""))[:160],
                "answer": draft.get("answer"),
            }
            for draft in drafts[:5]
        ],
    }


async def _extract_vision_text(
    data: bytes,
    *,
    max_pages: int,
    batch_pages: int,
    page_zoom: float,
    warnings: list[str],
) -> tuple[str, int, int]:
    chunks: list[str] = []
    attempted_batches = 0
    successful_batches = 0
    page_index = 0
    while page_index < max_pages:
        current_batch_pages = min(batch_pages, max_pages - page_index)
        attempted_batches += 1
        try:
            text = await question_bank_service._extract_scanned_pdf_text_with_vision(
                data,
                max_pages=current_batch_pages,
                start_page=page_index,
                page_zoom=page_zoom,
            )
        except RuntimeError as exc:
            warnings.append(f"视觉/OCR 第 {page_index + 1}-{page_index + current_batch_pages} 页失败：{exc}")
        else:
            if text:
                successful_batches += 1
                chunks.append(text)
        page_index += current_batch_pages
    return "\n".join(chunks), attempted_batches, successful_batches


async def evaluate_pdf(
    pdf_path: Path,
    *,
    expected_question_count: int | None = None,
    mock_ocr_text: str | None = None,
    use_vision: bool = False,
    vision_max_pages: int = 3,
    vision_batch_pages: int = 0,
    vision_page_zoom: float = 2.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    data = pdf_path.read_bytes()
    warnings: list[str] = []
    used_vision_ocr = False
    vision_batch_count = 0
    successful_vision_batches = 0
    source_text = ""
    try:
        source_text = question_bank_service._extract_pdf_text(data)
    except RuntimeError as exc:
        warnings.append(str(exc))

    if not source_text:
        if mock_ocr_text is not None:
            source_text = mock_ocr_text
            used_vision_ocr = True
            warnings.append("PDF 未抽取到文本，使用 mock OCR 文本评估")
        elif use_vision:
            if vision_batch_pages > 0:
                source_text, vision_batch_count, successful_vision_batches = await _extract_vision_text(
                    data,
                    max_pages=vision_max_pages,
                    batch_pages=vision_batch_pages,
                    page_zoom=vision_page_zoom,
                    warnings=warnings,
                )
            else:
                vision_batch_count = 1
                try:
                    source_text = await question_bank_service._extract_scanned_pdf_text_with_vision(
                        data,
                        max_pages=vision_max_pages,
                        page_zoom=vision_page_zoom,
                    )
                except RuntimeError as exc:
                    warnings.append(f"视觉/OCR 失败：{exc}")
                else:
                    successful_vision_batches = 1 if source_text else 0
            used_vision_ocr = bool(source_text)
            warnings.append(
                f"PDF 未抽取到文本，已调用视觉/OCR 评估前 {vision_max_pages} 页"
                f"（batch_pages={vision_batch_pages or vision_max_pages}, zoom={vision_page_zoom}）"
            )
        else:
            warnings.append("PDF 未抽取到文本；传 --use-vision 或 --mock-ocr-text-file 可评估扫描版")

    metrics = evaluate_extracted_text(source_text, expected_question_count=expected_question_count)
    metrics.update(
        {
            "path": str(pdf_path),
            "file_size": len(data),
            "used_vision_ocr": used_vision_ocr,
            "vision_batch_count": vision_batch_count,
            "successful_vision_batches": successful_vision_batches,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "warnings": warnings,
        }
    )
    return metrics


async def _main_async(args: argparse.Namespace) -> int:
    mock_ocr_text = Path(args.mock_ocr_text_file).read_text(encoding="utf-8") if args.mock_ocr_text_file else None
    results = []
    for raw_path in args.pdf_paths:
        pdf_path = Path(raw_path)
        results.append(
            await evaluate_pdf(
                pdf_path,
                expected_question_count=args.expected_question_count,
                mock_ocr_text=mock_ocr_text,
                use_vision=args.use_vision,
                vision_max_pages=args.vision_max_pages,
                vision_batch_pages=args.vision_batch_pages,
                vision_page_zoom=args.vision_page_zoom,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="评估题库 PDF/OCR 抽题效果")
    parser.add_argument("pdf_paths", nargs="+", help="待评估 PDF 路径")
    parser.add_argument("--expected-question-count", type=int, default=None, help="人工确认题目数，用于计算召回率")
    parser.add_argument("--mock-ocr-text-file", default=None, help="不调模型，使用该文本模拟扫描版 OCR 输出")
    parser.add_argument("--use-vision", action="store_true", help="文本抽取为空时调用 MiMo 视觉 OCR")
    parser.add_argument("--vision-max-pages", type=int, default=3, help="--use-vision 时最多渲染并识别的页数")
    parser.add_argument("--vision-batch-pages", type=int, default=0, help="--use-vision 时每批识别页数；0 表示一次性识别")
    parser.add_argument("--vision-page-zoom", type=float, default=2.0, help="--use-vision 时 PDF 渲染倍率；大图失败时可降到 1.0")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
