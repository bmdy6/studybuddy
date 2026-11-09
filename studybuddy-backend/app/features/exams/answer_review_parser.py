"""拍题作答核对解析。

从 OCR 产出的 Markdown 里提取每道题的学生作答核对项（PhotoAnswerReviewItem）。
该业务属于 exams 域，原寄居在 materials 域的 markdown_extraction_service 内，
迁出后 markdown_extraction_service 不再反向依赖 exams schema（§1 单向）。

共享的纯解析 helper（is_unclear_student_answer / _extract_question_no_from_line）
仍留在 materials 域的 markdown_extraction_service，因 normalize 亦依赖它们；
本模块单向跨域复用（§1），不引入反向依赖。
"""

from __future__ import annotations

import re
from typing import Literal

from app.features.exams.schemas.exam_batch import PhotoAnswerReviewItem
from app.features.materials.markdown_extraction_service import (  # 跨域单向：normalize 亦依赖，留 materials 复用（§1）
    _extract_question_no_from_line,
    is_unclear_student_answer,
)


def extract_answer_review_items(markdown: str) -> list[PhotoAnswerReviewItem]:
    items: list[PhotoAnswerReviewItem] = _extract_table_answer_review_items(markdown)
    seen_question_nos = {item.question_no for item in items}
    current_no: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_no, current_lines, seen_question_nos
        if not current_no or not current_lines:
            current_lines = []
            return
        if current_no in seen_question_nos:
            current_lines = []
            return
        block = "\n".join(current_lines)
        answer_match = re.search(r"学生作答\s*[：:]\s*(.+?)(?=\s*作答置信度\s*[：:]|\s*需确认\s*[：:]|$)", block)
        if not answer_match:
            current_lines = []
            return
        detected = _clean_detected_answer(answer_match.group(1))
        confidence = _extract_answer_confidence(block)
        reason = _extract_review_reason(block, detected)
        needs_review = bool(reason) or confidence == "low" or is_unclear_student_answer(detected)
        if is_unclear_student_answer(detected) and not reason:
            reason = "学生作答看不清"
        items.append(
            PhotoAnswerReviewItem(
                question_no=current_no,
                detected_answer=detected,
                confirmed_answer=None,
                confidence=confidence,
                needs_review=needs_review,
                review_reason=reason,
                answer_type=_infer_answer_type(detected),
                source_excerpt=block[:240],
            )
        )
        seen_question_nos.add(current_no)
        current_lines = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = _clean_markdown_list_line(line)
        question_no = _extract_question_no_from_line(line)
        if question_no:
            flush()
            current_no = question_no
        if current_no:
            current_lines.append(line)
    flush()
    return items


def _extract_table_answer_review_items(markdown: str) -> list[PhotoAnswerReviewItem]:
    items: list[PhotoAnswerReviewItem] = []
    headers: list[str] | None = None
    indexes: dict[str, int] = {}

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("|"):
            headers = None
            indexes = {}
            continue

        cells = _split_markdown_table_row(line)
        if not cells:
            continue
        if _is_markdown_table_separator(cells):
            continue
        if "学生作答" in cells:
            headers = cells
            indexes = {header: idx for idx, header in enumerate(headers)}
            continue
        if not headers or "学生作答" not in indexes:
            continue

        answer_idx = indexes["学生作答"]
        no_idx = indexes.get("题号", 0)
        confidence_idx = indexes.get("作答置信度")
        reason_idx = indexes.get("需确认")
        if len(cells) <= max(answer_idx, no_idx):
            continue

        detected = _clean_detected_answer(cells[answer_idx])
        if not detected:
            continue
        question_no = _normalize_question_no(cells[no_idx])
        if not question_no:
            continue
        confidence = _extract_answer_confidence(
            f"作答置信度：{cells[confidence_idx]}" if confidence_idx is not None and len(cells) > confidence_idx else ""
        )
        reason = _extract_review_reason(
            f"需确认：{cells[reason_idx]}" if reason_idx is not None and len(cells) > reason_idx else "",
            detected,
        )
        needs_review = bool(reason) or confidence == "low" or is_unclear_student_answer(detected)
        if is_unclear_student_answer(detected) and not reason:
            reason = "学生作答看不清"
        items.append(
            PhotoAnswerReviewItem(
                question_no=question_no,
                detected_answer=detected,
                confirmed_answer=None,
                confidence=confidence,
                needs_review=needs_review,
                review_reason=reason,
                answer_type=_infer_answer_type(detected),
                source_excerpt=line[:240],
            )
        )
    return items


def _split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_table_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _normalize_question_no(value: str) -> str:
    clean = value.strip()
    clean = re.sub(r"`([^`]*)`", r"\1", clean)
    clean = clean.strip(" 　[]（）()【】")
    numeric = re.search(r"\d+", clean)
    if numeric and re.fullmatch(r"(?:第)?\s*\d+\s*(?:题)?", clean):
        return numeric.group(0)
    return clean


def _clean_markdown_list_line(line: str) -> str:
    return re.sub(r"^[-*+]\s*", "", line).strip()


def _clean_detected_answer(answer: str) -> str:
    answer = answer.strip()
    answer = re.sub(r"\s*`{3,}\s*$", "", answer).strip()
    answer = re.sub(r"`([^`]*)`", r"\1", answer)
    answer = re.sub(r"\*\*([^*]*)\*\*", r"\1", answer)
    return answer.strip()


def _extract_answer_confidence(block: str) -> Literal["high", "medium", "low"]:
    match = re.search(r"作答置信度\s*[：:]\s*(.+)", block)
    if not match:
        return "low"
    value = match.group(1)
    if "中" in value or "medium" in value.lower():
        return "medium"
    if "高" in value or "high" in value.lower():
        return "high"
    return "low"


def _extract_review_reason(block: str, answer: str) -> str | None:
    match = re.search(r"需确认\s*[：:]\s*(.+)", block)
    if match:
        value = match.group(1).strip()
        if value and not re.search(r"^(无|无需|没有|否)$", value) and not re.search(r"(清晰|明确|无需确认|不需要确认)", value):
            return value
    if is_unclear_student_answer(answer):
        return "学生作答看不清"
    return None


def _infer_answer_type(answer: str) -> Literal["choice", "text", "unknown"]:
    clean = answer.strip().upper()
    if re.fullmatch(r"[A-E](?:\s*[,，、]\s*[A-E])*", clean):
        return "choice"
    if is_unclear_student_answer(answer):
        return "unknown"
    return "text"
