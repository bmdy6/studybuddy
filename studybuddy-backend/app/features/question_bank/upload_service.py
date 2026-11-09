"""试卷上传 + PDF/扫描 OCR（从 question_bank_service 拆出，技术债中6）。"""

from __future__ import annotations



import io
import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus
from sqlalchemy.orm import Session
from app.models.question_bank import QuestionBankPaper
from app.features.materials.markdown_extraction_service import extract_llm_message_text
from app.prompts import load
from app.utils.image import encode_bytes_for_vision
from .schemas import ValidateUploadedPaperFileResponse


from .parsers import _clean_text, _estimate_question_count, _extract_visible_text, _looks_like_pdf
from .scoring import _hash_url


_ANSWER_SIGNALS = ("答案", "参考答案", "答案解析", "解析", "answer", "参考解答")
_MAX_UPLOAD_VALIDATION_BYTES = 8 * 1024 * 1024


def _extract_pdf_text(data: bytes, max_pages: int = 12) -> str:
    """从文本型 PDF 抽取文字；扫描版通常返回空。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - CI 会安装依赖，本地缺依赖时给清晰错误
        raise RuntimeError("缺少 pypdf，无法解析 PDF 文本") from exc

    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages[:max_pages]:
        chunks.append(page.extract_text() or "")
    return _clean_text("\n".join(chunks))


def _extract_uploaded_paper_text(filename: str, content_type: str | None, data: bytes) -> tuple[str, str, list[str]]:
    clean_filename = filename or "upload"
    normalized_content_type = content_type or ""
    warnings: list[str] = []
    source_type = "uploaded_text"
    text = ""

    is_pdf = _looks_like_pdf(normalized_content_type, clean_filename, data)
    if is_pdf:
        source_type = "uploaded_pdf"
        try:
            text = _extract_pdf_text(data)
        except Exception as exc:  # noqa: BLE001 - 上传文件质量不可控，统一返回人工处理建议
            warnings.append(f"PDF 文本抽取失败：{str(exc)[:120]}")
            text = ""
        if not text:
            warnings.append("PDF 未抽取到文本，可能是扫描版，需要后续视觉 OCR 或人工确认")
    else:
        try:
            text = _extract_visible_text(data[:400_000].decode("utf-8", errors="ignore"))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"文本读取失败：{str(exc)[:120]}")
            text = ""
        if clean_filename.lower().endswith((".doc", ".docx", ".xls", ".xlsx")):
            source_type = "unsupported_office_file"
            warnings.append("暂不直接解析 Office 文件，请先导出为 PDF 或文本后上传")
        elif "html" in normalized_content_type.lower() or clean_filename.lower().endswith((".html", ".htm")):
            source_type = "uploaded_html"
    return source_type, text, warnings


def validate_uploaded_paper_file(filename: str, content_type: str | None, data: bytes) -> ValidateUploadedPaperFileResponse:
    """校验人工上传试卷文件是否适合进入题库解析，当前只产出证据，不写库。"""
    clean_filename = filename or "upload"
    content_length = len(data)

    if content_length == 0:
        return ValidateUploadedPaperFileResponse(
            filename=clean_filename,
            content_type=content_type,
            source_type="empty_file",
            content_length=0,
            text_length=0,
            question_count_estimate=0,
            last_question_no=None,
            has_answer_signal=False,
            can_parse_text=False,
            suggested_status="rejected",
            warnings=["文件为空，无法校验"],
            preview_text=None,
        )
    source_type, text, warnings = _extract_uploaded_paper_text(clean_filename, content_type, data)
    if content_length > _MAX_UPLOAD_VALIDATION_BYTES:
        warnings.append("文件超过 8MB，本次只做基础校验，正式解析前建议拆分或压缩")

    question_count, last_question_no = _estimate_question_count(text)
    has_answer = any(signal.lower() in text.lower() for signal in _ANSWER_SIGNALS)
    can_parse_text = bool(text and question_count > 0 and source_type != "unsupported_office_file")
    suggested_status = "candidate"
    if source_type == "unsupported_office_file":
        suggested_status = "rejected"
    elif can_parse_text and question_count >= 6 and has_answer:
        suggested_status = "confirmed"
    elif not can_parse_text:
        suggested_status = "candidate"

    if text and question_count < 3:
        warnings.append("识别到的题号较少，可能不是完整试卷或只包含前几题")
    if text and not has_answer:
        warnings.append("未识别到答案/解析信号，入库前需要人工补充或确认答案")

    return ValidateUploadedPaperFileResponse(
        filename=clean_filename,
        content_type=content_type,
        source_type=source_type,
        content_length=content_length,
        text_length=len(text),
        question_count_estimate=question_count,
        last_question_no=last_question_no,
        has_answer_signal=has_answer,
        can_parse_text=can_parse_text,
        suggested_status=suggested_status,
        warnings=warnings,
        preview_text=text[:800] if text else None,
    )


def create_uploaded_paper_source(
    db: Session,
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    title: str | None,
    grade: str,
    subject: str,
    province: str | None = None,
    city: str | None = None,
    district: str | None = None,
    school: str | None = None,
    semester: str | None = None,
    textbook_version: str | None = None,
    exam_type: str | None = None,
    year: int | None = None,
    created_by: int | None = None,
) -> tuple[QuestionBankPaper, ValidateUploadedPaperFileResponse]:
    validation = validate_uploaded_paper_file(filename, content_type, data)
    if not validation.can_parse_text:
        raise ValueError("上传文件未抽取到可解析题目文本，请先换成文本型 PDF/TXT，或走扫描版 OCR 流程")

    _, extracted_text, _ = _extract_uploaded_paper_text(filename, content_type, data)
    file_hash = hashlib.sha256(data).hexdigest()
    clean_filename = _clean_text(filename or "upload")[:160]
    source_url = f"upload://question-bank/{file_hash}/{quote_plus(clean_filename)}"
    url_hash = _hash_url(source_url)
    paper_title = _clean_text(title or clean_filename or "人工上传试卷")[:300]
    snippet = _clean_text(f"{validation.source_type} {validation.question_count_estimate}题 答案信号:{'有' if validation.has_answer_signal else '无'}")
    confidence = 82 if validation.suggested_status == "confirmed" else 60
    status = validation.suggested_status if validation.suggested_status in {"candidate", "confirmed", "rejected"} else "candidate"
    raw_meta = {
        "query": "manual_upload",
        "source_adapter": "manual_upload",
        "manual_upload": True,
        "uploaded_file": {
            "filename": clean_filename,
            "content_type": content_type,
            "file_hash": file_hash,
            "content_length": validation.content_length,
            "source_type": validation.source_type,
            "extracted_text": extracted_text[:200_000],
            "validation": validation.model_dump(),
        },
        "review": {
            "verdict": "formal_ready" if status == "confirmed" else "needs_manual",
            "confidence": confidence,
            "completeness": "likely_full" if status == "confirmed" else "partial",
            "suggested_status": status,
            "evidence": {
                "content_type": content_type or "",
                "content_length": validation.content_length,
                "text_length": validation.text_length,
                "question_count_estimate": validation.question_count_estimate,
                "last_question_no": validation.last_question_no,
                "has_answer_signal": validation.has_answer_signal,
                "manual_upload": True,
            },
            "reasons": ["人工上传文件已通过文本校验，进入候选解析队列"],
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    existing = db.query(QuestionBankPaper).filter(QuestionBankPaper.source_url_hash == url_hash).first()
    if existing:
        existing.title = paper_title or existing.title
        existing.snippet = snippet
        existing.province = province or existing.province
        existing.city = city or existing.city
        existing.district = district or existing.district
        existing.school = school or existing.school
        existing.grade = grade or existing.grade
        existing.semester = semester or existing.semester
        existing.subject = subject or existing.subject
        existing.textbook_version = textbook_version or existing.textbook_version
        existing.exam_type = exam_type or existing.exam_type
        existing.year = year or existing.year
        existing.availability_level = "A" if status == "confirmed" else "B"
        existing.risk_level = "low"
        existing.status = status
        existing.confidence = confidence
        existing.raw_meta = {**(existing.raw_meta or {}), **raw_meta}
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing, validation

    paper = QuestionBankPaper(
        title=paper_title,
        source_url=source_url,
        source_url_hash=url_hash,
        snippet=snippet,
        province=province,
        city=city,
        district=district,
        school=school,
        grade=grade,
        semester=semester,
        subject=subject,
        textbook_version=textbook_version,
        year=year,
        exam_type=exam_type,
        source_type="web_paper",
        availability_level="A" if status == "confirmed" else "B",
        risk_level="low",
        status=status,
        confidence=confidence,
        created_by=created_by,
        raw_meta=raw_meta,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper, validation


def _render_pdf_pages_to_png(data: bytes, max_pages: int = 3, start_page: int = 0, page_zoom: float = 2.0) -> list[bytes]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("缺少 pymupdf，无法渲染扫描版 PDF") from exc

    images: list[bytes] = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            first_page = max(0, start_page)
            last_page = min(len(doc), first_page + max_pages)
            for page_index in range(first_page, last_page):
                page = doc.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(page_zoom, page_zoom), alpha=False)
                images.append(pixmap.tobytes("png"))
    except Exception as exc:  # noqa: BLE001 - 外部 PDF 质量不可控，统一降级为可展示 warning
        raise RuntimeError(f"扫描版 PDF 渲染失败：{exc}") from exc
    return images


async def _extract_scanned_pdf_text_with_vision(data: bytes, max_pages: int = 3, start_page: int = 0, page_zoom: float = 2.0) -> str:
    """扫描版 PDF 兜底：渲染前几页为图片后交给视觉模型转写题目文本。"""
    from app.core import ai_service

    images = _render_pdf_pages_to_png(data, max_pages=max_pages, start_page=start_page, page_zoom=page_zoom)
    if not images:
        return ""
    content: list[dict[str, Any]] = [encode_bytes_for_vision(image) for image in images]
    content.append(
        {
            "type": "text",
            "text": load("material_vision/scanned_pdf_transcribe"),
        }
    )
    resp = await ai_service.call_llm(messages=[{"role": "user", "content": content}], max_tokens=3500)
    return _clean_text(extract_llm_message_text(resp.choices[0].message))
