"""考试批次服务：错题导入全流程。

阶段一：批量上传照片 → 存子文件夹+重命名 → 创建批次
阶段二：img2pdf 合成 PDF（留档） + MiMo 视觉解析作答
阶段三：判分（ask 分数/答案）→ 标注 → 入错题本
"""

import json
import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.constants import ALLOWED_EXAM_PHOTO_EXTENSIONS
from app.prompts import load
from app.models.exam_batch import ExamBatch
import app
from app.models.material import Material
from app.features.materials.markdown_extraction_service import extract_llm_message_text, is_unclear_student_answer
from .schemas.exam_batch import (
    BatchItem,
    ParsedQuestion,
    ParseResult,
    PhotoAnswerReviewItem,
    PhotoAnswerReviewState,
)

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(app.__file__)), "uploads", "materials", "exams")  # app/__init__.py 上两级 = studybuddy-backend/，不依赖本文件层级
EXAM_UPLOAD_REL_ROOT = "materials/exams"


def _to_item(b: ExamBatch) -> BatchItem:
    return BatchItem(
        id=b.id,
        student_id=b.student_id,
        subject=b.subject,
        exam_name=b.exam_name,
        exam_date=b.exam_date,
        photo_material_ids=b.photo_material_ids or [],
        parsed_pdf_ref=b.parsed_pdf_ref,
        folder_name=b.folder_name,
        status=b.status,
        created_at=b.created_at.strftime("%Y-%m-%d %H:%M:%S") if b.created_at else "",
    )


def to_item(batch: ExamBatch) -> BatchItem:
    """公开的批次响应转换入口，供 router/API 复用。"""
    return _to_item(batch)


def create_batch(db: Session, student_id: int, subject: str, exam_name: str, exam_date: str) -> BatchItem:
    """创建考试批次。子文件夹名：{id}_{学科}_{考试名}_{日期}。"""
    subject = (subject or "auto").strip() or "auto"
    batch = ExamBatch(
        student_id=student_id,
        subject=subject,
        exam_name=exam_name,
        exam_date=exam_date,
        photo_material_ids=[],
        status="uploaded",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    # 生成子文件夹名（id 已拿到）
    safe_name = re.sub(r"[^\w\u4e00-\u9fa5\-]", "_", exam_name)
    batch.folder_name = f"{batch.id}_{subject}_{safe_name}_{exam_date}"
    db.commit()
    db.refresh(batch)
    return _to_item(batch)


def save_photo_to_batch(
    db: Session,
    batch: ExamBatch,
    filename: str,
    file_bytes: bytes,
    uploader_id: int,
    page_type: str = "试卷",  # 答题卡 / 试卷
) -> Material:
    """把一张照片存到批次子文件夹 + 重命名 + 进素材库。

    重命名：{序号}_{答题卡|试卷}_{第N页}.jpg
    content_ref: local:materials/exams/{folder_name}/{新文件名}
    """
    folder = batch.folder_name or f"batch_{batch.id}"
    folder_path = os.path.join(UPLOAD_ROOT, folder)
    os.makedirs(folder_path, exist_ok=True)

    # 序号 = 已有照片数 + 1
    seq = len(batch.photo_material_ids or []) + 1
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXAM_PHOTO_EXTENSIONS:
        raise ValueError("不支持的照片格式")
    new_name = f"{seq:02d}_{page_type}_第{seq}页.{ext}"
    rel_path = f"{EXAM_UPLOAD_REL_ROOT}/{folder}/{new_name}"
    abs_path = os.path.join(UPLOAD_ROOT, folder, new_name)

    with open(abs_path, "wb") as f:
        f.write(file_bytes)

    # 进素材库（source 列是 enum('teacher','student')，用上传者角色）
    material = Material(
        name=new_name,
        type="image",
        source="teacher" if uploader_id != batch.student_id else "student",
        knowledge_tags=[] if batch.subject == "auto" else [batch.subject],
        uploaded_by=uploader_id,
        content_ref=f"local:{rel_path}",
        mode="study",  # 试卷 OCR 素材属学习模式（与学科体系绑定）
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    # 关联到批次
    ids = list(batch.photo_material_ids or [])
    ids.append(material.id)
    batch.photo_material_ids = ids
    db.commit()
    return material


def get_batch(db: Session, batch_id: int) -> ExamBatch | None:
    return db.get(ExamBatch, batch_id)


def is_empty_uploaded_batch(batch: ExamBatch) -> bool:
    """判断批次是否仍是上传前的空壳，可安全清理。"""
    return batch.status == "uploaded" and not (batch.photo_material_ids or []) and not batch.parsed_pdf_ref


def list_batches(db: Session, student_id: int) -> list[BatchItem]:
    batches = db.query(ExamBatch).filter(ExamBatch.student_id == student_id).order_by(ExamBatch.id.desc()).all()
    return [_to_item(b) for b in batches if not is_empty_uploaded_batch(b)]


async def parse_photos_and_mark_parsed(db: Session, batch: ExamBatch) -> ParseResult:
    """解析批次照片并在 service 内完成批次状态流转。"""
    result = await parse_photos_with_vision(db, batch)
    batch.status = "parsed"
    db.commit()
    db.refresh(batch)
    return result


def delete_empty_batch(db: Session, batch: ExamBatch) -> bool:
    """删除上传失败留下的空批次；已有照片/PDF/解析结果的批次不允许删除。"""
    if not is_empty_uploaded_batch(batch):
        return False
    folder = batch.folder_name or f"batch_{batch.id}"
    folder_path = os.path.join(UPLOAD_ROOT, folder)
    db.delete(batch)
    db.commit()
    if os.path.isdir(folder_path):
        try:
            os.rmdir(folder_path)
        except OSError:
            pass
    return True


def build_answer_review_state(
    batch: ExamBatch,
    recognized_markdown: str,
    items: list[PhotoAnswerReviewItem],
) -> PhotoAnswerReviewState:
    """构造并持久化拍题逐题核对状态。"""
    state = PhotoAnswerReviewState(
        batch_id=batch.id,
        recognized_markdown=recognized_markdown,
        items=items,
        status="pending_review",
        confirmed_at=None,
    )
    batch.recognized_markdown = recognized_markdown
    batch.answer_review_state = state.model_dump(mode="json")
    return state


def get_answer_review_state(batch: ExamBatch) -> PhotoAnswerReviewState | None:
    """读取批次上的拍题作答核对状态。"""
    if not batch.answer_review_state:
        return None
    return PhotoAnswerReviewState(**batch.answer_review_state)


def confirm_answer_review(
    db: Session,
    batch: ExamBatch,
    items: list[PhotoAnswerReviewItem],
) -> PhotoAnswerReviewState:
    """确认或修正拍题作答，低置信项必须被用户处理。"""
    for item in items:
        confirmed = (item.confirmed_answer or "").strip()
        detected = (item.detected_answer or "").strip()
        needs_manual_decision = item.needs_review or item.confidence == "low" or is_unclear_student_answer(detected)
        if needs_manual_decision and not item.skipped and not confirmed:
            raise ValueError(f"第{item.question_no}题作答需要先确认、修正或跳过")
        if not item.confirmed_answer and not item.skipped and detected:
            item.confirmed_answer = detected

    confirmed_at = datetime.now()
    state = PhotoAnswerReviewState(
        batch_id=batch.id,
        recognized_markdown=batch.recognized_markdown or "",
        items=items,
        status="confirmed",
        confirmed_at=confirmed_at,
    )
    batch.answer_review_state = state.model_dump(mode="json")
    batch.answer_review_confirmed_at = confirmed_at
    db.commit()
    db.refresh(batch)
    return state


def confirmed_review_to_parsed_questions(batch: ExamBatch) -> list[ParsedQuestion]:
    """把已确认的逐题作答转换成判分/批改可用的题号答案。"""
    state = get_answer_review_state(batch)
    if not state or state.status != "confirmed":
        return []

    questions: list[ParsedQuestion] = []
    for item in state.items:
        if item.skipped:
            continue
        answer = (item.confirmed_answer or item.detected_answer or "").strip()
        if not answer:
            continue
        questions.append(ParsedQuestion(no=item.question_no, answer=answer))
    return questions


def _extract_json_text(raw: str) -> str:
    """从模型输出中提取 JSON 对象文本。"""
    raw_clean = re.sub(r"^```json\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    if raw_clean.startswith(("{", "[")):
        return raw_clean
    match = re.search(r"(\{.*\}|\[.*\])", raw_clean, flags=re.DOTALL)
    return match.group(0) if match else raw_clean


def _parse_questions_from_model_text(raw: str) -> list[ParsedQuestion]:
    """从模型文本中解析题目，兼容完整 JSON 和 reasoning 中的单题片段。"""
    raw_clean = _extract_json_text(raw)
    try:
        data = json.loads(raw_clean)
        items = data if isinstance(data, list) else data.get("questions", []) if isinstance(data, dict) else []
        return [ParsedQuestion(**q) for q in items]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    questions: list[ParsedQuestion] = []
    seen: set[str] = set()
    for match in re.finditer(r'\{[^{}]*"no"\s*:\s*"[^"]+"[^{}]*"answer"\s*:\s*"[^"]*"[^{}]*\}', raw):
        try:
            item = json.loads(match.group(0))
            question = ParsedQuestion(**item)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if question.no == "题号" or question.no in seen:
            continue
        seen.add(question.no)
        questions.append(question)
    return questions


def synthesize_pdf(db: Session, batch: ExamBatch) -> str | None:
    """用 img2pdf 把批次照片合成一份 PDF（留档预览用，不参与识别）。

    返回 content_ref（local:materials/exams/{folder}/解析卷.pdf）。
    """
    import img2pdf  # 延迟导入，未装时不影响后端启动

    folder = batch.folder_name or f"batch_{batch.id}"
    folder_path = os.path.join(UPLOAD_ROOT, folder)
    # 收集照片文件（按序号排序）
    photos = sorted([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith((".jpg", ".jpeg", ".png"))])
    if not photos:
        return None

    pdf_path = os.path.join(folder_path, "解析卷.pdf")
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(photos, rotation=img2pdf.Rotation.ifvalid))

    rel = f"local:{EXAM_UPLOAD_REL_ROOT}/{folder}/解析卷.pdf"
    batch.parsed_pdf_ref = rel
    db.commit()
    return rel


async def parse_photos_with_vision(db: Session, batch: ExamBatch) -> ParseResult:
    """用 MiMo 视觉解析批次照片，返回每题作答。

    阶段二核心：照片直接给 MiMo（不转PDF，PDF只留档），让模型识别题号+作答+分数。
    """
    from app.core import ai_service
    from app.utils.image import encode_image_for_vision

    folder = batch.folder_name or f"batch_{batch.id}"
    folder_path = os.path.join(UPLOAD_ROOT, folder)
    photos = sorted([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith((".jpg", ".jpeg", ".png"))])
    if not photos:
        return ParseResult(batch_id=batch.id, questions=[], raw_text="无照片")

    # 构造多图消息（统一走 utils.image 压缩，避免大图直接嗂 LLM 浪费 token）
    content: list[dict[str, Any]] = [encode_image_for_vision(p) for p in photos]
    content.append(
        {
            "type": "text",
            "text": load("exam_vision/exam_photo_parse"),
        }
    )

    resp = await ai_service.call_llm(
        messages=[{"role": "user", "content": content}],
        max_tokens=2000,
    )
    raw = extract_llm_message_text(resp.choices[0].message)
    questions = _parse_questions_from_model_text(raw)
    return ParseResult(batch_id=batch.id, questions=questions, raw_text=raw)


def grade_and_save_errors(
    db: Session,
    batch: ExamBatch,
    parsed_questions: list[ParsedQuestion],
    grade_mode: str = "no_score_no_answer",  # has_score / no_score_has_answer / no_score_no_answer
    manual_scores: dict[str, int] | None = None,  # 题号->分数（has_score 模式用户确认的）
    standard_answers: dict[str, str] | None = None,  # 题号->标准答案（no_score_has_answer 模式）
) -> dict:
    """阶段三：判分 + 入错题本。

    三级判分逻辑（按 grade_mode）：
    - has_score：试卷上有老师批改分数 → 直接用 manual_scores，分数<60%判错
    - no_score_has_answer：无分数有答案 → 对照 standard_answers 判
    - no_score_no_answer：都没有 → 全部判错（保守，让用户确认）

    错题入库：判错后建虚拟试卷 + Question + ErrorBook（建试卷/记录/题目骨架复用 error_intake_service）。
    """
    from app.features.exams.error_intake_service import VirtualExamErrorItem, save_virtual_exam_errors

    exam_title = f"错题导入-{batch.exam_name}-{batch.exam_date}"
    error_items: list[VirtualExamErrorItem] = []
    total = len(parsed_questions)
    for q in parsed_questions:
        # 判分
        if grade_mode == "has_score" and manual_scores:
            score = manual_scores.get(q.no, 0)
            is_wrong = score < 60  # 满分100，<60判错
        elif grade_mode == "no_score_has_answer" and standard_answers:
            std = standard_answers.get(q.no, "")
            is_wrong = q.answer.strip().lower() != std.strip().lower()
        else:
            # no_score_no_answer：无法判，全部标为待确认（保守判错让用户复核）
            is_wrong = True

        if not is_wrong:
            continue

        # 题干=题号+作答，因为照片题不在系统题库
        error_items.append(
            VirtualExamErrorItem(
                stem=f"第{q.no}题（错题导入）作答：{q.answer}",
                answer_json={"answer": q.answer},  # NOT NULL，存学生作答
                tags=[batch.subject],
            )
        )

    result = save_virtual_exam_errors(
        db,
        student_id=batch.student_id,
        exam_title=exam_title,
        subject=batch.subject,
        error_items=error_items,
    )
    batch.status = "graded"
    db.commit()
    return {
        "batch_id": batch.id,
        "total_questions": total,
        "wrong_count": result["saved_count"],
        "exam_id": result["exam_id"],
        "grade_mode": grade_mode,
        "summary": f"共{total}题，判出{result['saved_count']}道错题，已入错题本",
    }
