from __future__ import annotations

import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core import ai_service
from app.prompts import load
from app.utils.image import encode_image_for_vision
from . import markdown_ocr_service


class MarkdownExtractionResult(BaseModel):
    markdown: str = ""
    confidence: str = "low"
    uncertain_points: list[str] = Field(default_factory=list)
    content_type: str = ""
    raw_text: str = ""
    provider: str = "mimo"
    elapsed_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


def normalize_markdown_extraction_result(raw_text: str) -> MarkdownExtractionResult:
    markdown = _strip_markdown_fence(raw_text.strip())
    confidence = _extract_markdown_confidence(markdown)
    uncertain_points = _extract_markdown_list_value(markdown, "需要人工确认的内容")
    content_types = _extract_markdown_list_value(markdown, "适合作为哪类学习素材")
    answer_review_lines, answer_uncertain_points = _extract_student_answer_review(markdown)
    uncertain_points = [
        point for point in uncertain_points if not _looks_like_content_type(point) and point not in content_types
    ]
    for point in answer_uncertain_points:
        if point not in uncertain_points:
            uncertain_points.append(point)
    markdown = _append_answer_review_section(markdown, answer_review_lines)
    return MarkdownExtractionResult(
        markdown=markdown,
        confidence=confidence,
        uncertain_points=uncertain_points,
        content_type=content_types[0] if content_types else "",
        raw_text=raw_text,
    )


def extract_llm_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content:
        return str(content)
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        return str(reasoning)
    extra = getattr(message, "model_extra", None) or {}
    if isinstance(extra, dict) and extra.get("reasoning_content"):
        return str(extra["reasoning_content"])
    return ""


async def recognize_images_to_markdown(
    image_paths: list[str],
    mode: Literal["homework_photo", "learning_material"],
) -> MarkdownExtractionResult:
    if not image_paths:
        raise ValueError("image_paths must not be empty")

    started = time.perf_counter()
    external_result = markdown_ocr_service.recognize_photos_to_markdown(image_paths)
    if external_result:
        result = normalize_markdown_extraction_result(external_result.markdown)
        result.provider = external_result.provider
        result.elapsed_ms = external_result.elapsed_ms
        result.warnings = external_result.warnings
        return result

    content = [encode_image_for_vision(path) for path in image_paths]
    prompt = load("material_vision/homework_markdown") if mode == "homework_photo" else load("material_vision/learning_material_markdown")
    content.append({"type": "text", "text": prompt})
    resp = await ai_service.call_llm(messages=[{"role": "user", "content": content}], max_tokens=2200)
    raw = extract_llm_message_text(resp.choices[0].message)
    result = normalize_markdown_extraction_result(raw)
    result.provider = "mimo"
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


def _strip_markdown_fence(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_student_answer_review(markdown: str) -> tuple[list[str], list[str]]:
    review_lines: list[str] = []
    uncertain_points: list[str] = []
    current_no = "未标题号"

    pending_answer: tuple[str, str] | None = None
    pending_low_confidence = False

    def flush_pending() -> None:
        nonlocal pending_answer, pending_low_confidence
        if not pending_answer:
            return
        question_label, answer = pending_answer
        if pending_low_confidence or is_unclear_student_answer(answer):
            point = f"{question_label}：学生作答需要确认"
            review_lines.append(f"- {point}")
            uncertain_points.append(point)
        else:
            review_lines.append(f"- {question_label}：学生作答已识别为 {answer}")
        pending_answer = None
        pending_low_confidence = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        question_no = _extract_question_no_from_line(line)
        if question_no and "学生作答" not in line:
            flush_pending()
            current_no = question_no
        answer_match = re.search(r"学生作答\s*[：:]\s*(.+)", line)
        if not answer_match:
            if pending_answer and _line_indicates_answer_needs_review(line):
                pending_low_confidence = True
            continue
        flush_pending()
        answer = answer_match.group(1).strip()
        question_label = f"第{current_no}题" if current_no != "未标题号" else "未标题号题"
        pending_answer = (question_label, answer)
        pending_low_confidence = is_unclear_student_answer(answer)
    flush_pending()
    return review_lines, uncertain_points


def _line_indicates_answer_needs_review(line: str) -> bool:
    if "需确认" in line and not re.search(r"需确认\s*[：:]\s*(无|无需|没有)", line):
        return True
    if "作答置信度" in line and any(token in line for token in ("低", "不确定", "看不清", "模糊")):
        return True
    return False


def _extract_question_no_from_line(line: str) -> str | None:
    clean = re.sub(r"^#+\s*", "", line).strip()
    if not clean:
        return None
    if "知识点" in clean:
        return None
    if line.startswith("#") and re.match(r"^\d+[.、：:]", clean):
        return None

    practice_match = re.match(r"^学以致用\s*(\d+)", clean)
    if practice_match:
        return f"学以致用{practice_match.group(1)}"

    paren_match = re.match(r"^[（(]\s*(\d+)\s*[）)]", clean)
    if paren_match:
        return paren_match.group(1)

    explicit_match = re.match(r"^第\s*(\d+)\s*题", clean)
    if explicit_match:
        return explicit_match.group(1)

    plain_match = re.match(r"^(\d+)[.、：:]\s+", clean)
    if plain_match:
        return plain_match.group(1)
    return None


def is_unclear_student_answer(answer: str) -> bool:
    clean = answer.strip().strip("。.;；")
    if not clean:
        return True
    unclear_tokens = ("[?]", "？", "?", "不清晰", "看不清", "无法识别", "不确定", "疑似", "模糊")
    return any(token in clean for token in unclear_tokens)


def _append_answer_review_section(markdown: str, review_lines: list[str]) -> str:
    if not review_lines or "学生作答核对" in markdown:
        return markdown
    return markdown.rstrip() + "\n\n## 学生作答核对\n" + "\n".join(review_lines)


def _extract_markdown_confidence(markdown: str) -> str:
    match = re.search(r"识别置信度\**[：:]\s*[^\d]*(\d{1,3})\s*%", markdown)
    if not match:
        label_match = re.search(r"识别置信度\**[：:][ \t]*(.+)", markdown)
        if not label_match:
            return "low"
        value = label_match.group(1)
        if "高" in value:
            return "high"
        if "中" in value:
            return "medium"
        return "low"
    score = int(match.group(1))
    if score >= 90:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


def _extract_markdown_list_value(markdown: str, label: str) -> list[str]:
    pattern = rf"{re.escape(label)}\**[：:][ \t]*(.*)"
    match = re.search(pattern, markdown)
    if match and match.group(1).strip():
        value = match.group(1).strip()
        value = re.sub(r"\s*`{3,}\s*$", "", value).strip()
        return _split_markdown_summary_value(value)

    values: list[str] = []
    lines = markdown.splitlines()
    label_index = next((idx for idx, line in enumerate(lines) if label in line), -1)
    if label_index < 0:
        return []
    for line in lines[label_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+[.、]\s*\**[^*]+?\**[：:]", stripped):
            break
        bullet = re.match(r"^[-*]\s+(.+)", stripped)
        if bullet:
            values.extend(_split_markdown_summary_value(bullet.group(1).strip()))
            continue
        if values:
            break
    return values


def _split_markdown_summary_value(value: str) -> list[str]:
    if not value or value in {"无", "暂无", "无明显"}:
        return []
    parts = re.split(r"[；;]\s*|、\s*", value)
    return [part.strip() for part in parts if part.strip()]


def _looks_like_content_type(value: str) -> bool:
    clean = value.strip()
    return clean.startswith("适合") and ("素材" in clean or "练习" in clean or "学习" in clean)
# agg-1
