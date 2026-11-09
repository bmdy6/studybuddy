"""拍题批改服务。"""

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.exam_batch import ExamBatch
from .schemas.photo_grading import PhotoGradingQuestion, PhotoGradingResult
from app.features.materials.markdown_extraction_service import MarkdownExtractionResult, normalize_markdown_extraction_result


class PhotoMarkdownResult(MarkdownExtractionResult):
    """拍题图片转 Markdown 的可确认识别稿。"""


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    return json.loads(text)


def normalize_photo_markdown_result(raw_text: str) -> PhotoMarkdownResult:
    """把视觉模型返回的 Markdown 识别稿归一化，保留可人工确认的信息。"""
    result = normalize_markdown_extraction_result(raw_text)
    return PhotoMarkdownResult(**result.model_dump())


def normalize_photo_grading_result(raw_text: str) -> PhotoGradingResult:
    """把模型返回归一化成稳定的逐题批改结构。"""
    payload = _extract_json_object(raw_text)
    subject = str(payload.get("subject") or "").strip()
    questions: list[PhotoGradingQuestion] = []
    for item in payload.get("questions", []):
        q = PhotoGradingQuestion(**item)
        if not q.correct_answer or q.confidence not in {"high", "medium"}:
            q.needs_review = True
        questions.append(q)
    if not subject:
        subject = _infer_subject_from_questions(questions)
    return PhotoGradingResult(subject=subject, questions=questions, raw_text=raw_text)


def _infer_subject_from_questions(questions: list[PhotoGradingQuestion]) -> str:
    for q in questions:
        for tag in q.knowledge_tags:
            clean = str(tag).strip()
            if clean:
                return clean
    return "其他"


def save_confirmed_homework_errors(
    db: Session,
    batch: ExamBatch,
    questions: list[PhotoGradingQuestion],
    subject: str | None = None,
) -> dict[str, Any]:
    """保存用户确认的拍题错题，复用错题本 upsert 去重累加。"""
    from app.features.exams.error_intake_service import VirtualExamErrorItem, save_virtual_exam_errors

    detected_subject = (subject or "").strip() or (batch.subject if batch.subject != "auto" else "")
    if not detected_subject:
        detected_subject = _infer_subject_from_questions(questions)
    exam_title = f"拍题批改-{batch.exam_name}-{batch.exam_date}"

    error_items: list[VirtualExamErrorItem] = []
    for q in questions:
        if q.is_correct is True:
            continue
        no = q.no or "未知"
        stem_text = q.stem or f"学生作答：{q.student_answer}"
        tags = list(q.knowledge_tags or [])
        if detected_subject and detected_subject not in tags:
            tags.insert(0, detected_subject)
        error_items.append(
            VirtualExamErrorItem(
                stem=f"第{no}题：{stem_text}",
                answer_json={
                    "answer": q.correct_answer,
                    "student_answer": q.student_answer,
                    "error_point": q.error_point,
                    "explanation": q.explanation,
                },
                tags=tags,
            )
        )

    result = save_virtual_exam_errors(
        db,
        student_id=batch.student_id,
        exam_title=exam_title,
        subject=detected_subject,
        error_items=error_items,
    )
    batch.status = "graded"
    db.commit()
    return {"batch_id": batch.id, "saved_count": result["saved_count"], "exam_id": result["exam_id"]}
