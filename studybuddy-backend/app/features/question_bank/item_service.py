"""题目解析 + 题库 CRUD（从 question_bank_service 拆出，技术债中6）。"""

from __future__ import annotations



import re
from typing import Any
from sqlalchemy.orm import Session
from app.models.question_bank import QuestionBankItem, QuestionBankPaper, QuestionBankSource
from .schemas import ParsePaperSourceResponse, QuestionBankItem as QuestionBankItemSchema, QuestionBankPaperItem, SearchPaperSourcesRequest


from . import search_service, source_service, upload_service
from .parsers import _clean_text
from .scoring import _hash_question
from .search_service import save_paper_candidates


def _infer_question_type(stem: str) -> str:
    if re.search(r"\b[A-D][.．、]", stem) or "选择" in stem:
        return "single_choice"
    if "填空" in stem or "____" in stem or "___" in stem:
        return "fill_blank"
    return "short_answer"


def _extract_options(stem: str) -> list[str] | None:
    matches = re.findall(r"(?:^|\s)[A-D][.．、]\s*(.*?)(?=\s[A-D][.．、]\s*|$)", stem)
    cleaned = [_clean_text(item) for item in matches if _clean_text(item)]
    return cleaned or None


def _trim_question_noise(body: str) -> str:
    """去掉 PDF 连续文本里常见的下一节标题和作答提示，避免混入上一题题干。"""
    noise_patterns = [
        r"\s+[一二三四五六七八九十]+、(?:词汇|单项选择|动词填空|句型转换|阅读理解|完成句子|完形填空|书面表达)[^0-9]*",
        r"\s+做完后请.*",
        r"\s+不会的题.*",
    ]
    end = len(body)
    for pattern in noise_patterns:
        match = re.search(pattern, body)
        if match:
            end = min(end, match.start())
    return _clean_text(body[:end])


def _parse_questions_from_text(text: str) -> list[dict[str, object]]:
    """从网页文本中切出题目草稿。只做待确认入库，不自动批准。"""
    compact = re.sub(r"\s+", " ", text)
    pattern = re.compile(r"(?:^|\s)(\d{1,2})[.．、]\s*(.*?)(?=\s\d{1,2}[.．、]\s|$)")
    drafts: list[dict[str, object]] = []
    for match in pattern.finditer(compact):
        no = match.group(1)
        body = _clean_text(match.group(2))
        if len(body) < 8:
            continue
        answer = None
        answer_match = re.search(r"(?:答案|参考答案|Answer)[:：]\s*([^。；;]+)", body, flags=re.I)
        if answer_match:
            answer = _clean_text(answer_match.group(1))
            body = _clean_text(body[: answer_match.start()])
        body = _trim_question_noise(body)
        if not body:
            continue
        drafts.append(
            {
                "question_no": no,
                "stem": body[:1200],
                "answer": answer,
                "question_type": _infer_question_type(body),
                "options": _extract_options(body),
                "raw_text": match.group(0)[:2000],
            }
        )
    return drafts


def _enrich_existing_question_bank_item(item: QuestionBankItem, draft: dict[str, object]) -> bool:
    changed = False
    draft_options = draft.get("options")
    if isinstance(draft_options, list) and len(draft_options) > len(item.options or []):
        item.options = draft_options
        changed = True
    draft_answer = draft.get("answer")
    if draft_answer and not item.answer:
        item.answer = str(draft_answer)
        changed = True
    draft_question_type = str(draft.get("question_type") or "")
    if draft_question_type and item.question_type in {"short_answer", ""} and draft_question_type != item.question_type:
        item.question_type = draft_question_type
        changed = True
    return changed


def _to_bank_item(item: QuestionBankItem) -> QuestionBankItemSchema:
    return QuestionBankItemSchema(
        id=item.id,
        subject=item.subject,
        grade=item.grade,
        semester=item.semester,
        question_type=item.question_type,
        stem=item.stem,
        options=item.options,
        answer=item.answer,
        explanation=item.explanation,
        knowledge_tags=item.knowledge_tags or [],
        difficulty=item.difficulty,
        status=item.status,
        duplicate_key=item.duplicate_key,
    )


def list_question_bank_items(
    db: Session,
    *,
    status: str | None = "pending",
    subject: str | None = None,
    grade: str | None = None,
    keyword: str | None = None,
    limit: int = 80,
) -> list[QuestionBankItemSchema]:
    query = db.query(QuestionBankItem)
    if status:
        query = query.filter(QuestionBankItem.status == status)
    if subject:
        query = query.filter(QuestionBankItem.subject == subject)
    if grade:
        query = query.filter(QuestionBankItem.grade == grade)
    if keyword:
        query = query.filter(QuestionBankItem.stem.like(f"%{keyword.strip()}%"))
    items = query.order_by(QuestionBankItem.id.desc()).limit(limit).all()
    return [_to_bank_item(item) for item in items]


def update_question_bank_item_status(db: Session, item_id: int, status: str) -> QuestionBankItemSchema | None:
    item = db.get(QuestionBankItem, item_id)
    if not item:
        return None
    item.status = status
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_bank_item(item)


def _parsed_item_status(paper: QuestionBankPaper, draft: dict[str, Any]) -> str:
    if paper.status == "confirmed" and draft.get("answer"):
        return "approved"
    return "pending"


async def parse_paper_source_to_items(db: Session, paper_id: int) -> ParsePaperSourceResponse | None:
    paper = db.get(QuestionBankPaper, paper_id)
    if not paper:
        return None
    warnings: list[str] = []
    review = (paper.raw_meta or {}).get("review") or {}
    if review and review.get("verdict") not in {"formal_ready", "needs_manual"}:
        warnings.append(f"当前初审结论为 {review.get('verdict')}，解析结果仅作为待确认草稿")

    uploaded_file = (paper.raw_meta or {}).get("uploaded_file") or {}
    uploaded_text = uploaded_file.get("extracted_text") if isinstance(uploaded_file, dict) else None
    source_text = str(uploaded_text or "")
    used_vision_ocr = False
    if source_text:
        warnings.append("已使用人工上传文件的文本校验结果进入解析队列")
    else:
        fetched = await source_service.fetch_paper_source_preview(paper)
        if not fetched.get("ok"):
            return ParsePaperSourceResponse(paper_id=paper.id, parsed_count=0, saved_count=0, items=[], warnings=["来源不可访问，无法解析"])
        source_text = str(fetched.get("text", ""))
    if not uploaded_text and fetched.get("is_pdf"):
        content_bytes = fetched.get("content_bytes")
        if not isinstance(content_bytes, bytes):
            return ParsePaperSourceResponse(
                paper_id=paper.id,
                parsed_count=0,
                saved_count=0,
                items=[],
                warnings=["PDF 内容未下载成功，无法解析"],
            )
        try:
            source_text = upload_service._extract_pdf_text(content_bytes)
        except RuntimeError as exc:
            return ParsePaperSourceResponse(paper_id=paper.id, parsed_count=0, saved_count=0, items=[], warnings=[str(exc)])
        if not source_text:
            try:
                source_text = await upload_service._extract_scanned_pdf_text_with_vision(content_bytes)
            except RuntimeError as exc:
                return ParsePaperSourceResponse(
                    paper_id=paper.id,
                    parsed_count=0,
                    saved_count=0,
                    items=[],
                    warnings=[str(exc)],
                )
            if not source_text:
                return ParsePaperSourceResponse(
                    paper_id=paper.id,
                    parsed_count=0,
                    saved_count=0,
                    items=[],
                    warnings=["PDF 未抽取到文本，视觉/OCR 也未识别到可用题目"],
                )
            used_vision_ocr = True
            warnings.append("PDF 未抽取到文本，已使用视觉/OCR 兜底解析，结果仍需人工审核")

    drafts = _parse_questions_from_text(source_text)
    saved: list[QuestionBankItem] = []
    missing_answer_count = 0
    for draft in drafts:
        stem = str(draft["stem"])
        answer = draft.get("answer")
        item_status = _parsed_item_status(paper, draft)
        if paper.status == "confirmed" and item_status == "pending":
            missing_answer_count += 1
        duplicate_key = _hash_question(stem, str(answer) if answer else None)
        item = db.query(QuestionBankItem).filter(QuestionBankItem.duplicate_key == duplicate_key).first()
        if not item:
            item = QuestionBankItem(
                subject=paper.subject,
                grade=paper.grade,
                semester=paper.semester,
                question_type=str(draft["question_type"]),
                stem=stem,
                options=draft.get("options"),
                answer=str(answer) if answer else None,
                knowledge_tags=[paper.subject] if paper.subject else [],
                status=item_status,
                duplicate_key=duplicate_key,
                raw_meta={
                    "paper_id": paper.id,
                    "parser": "vision_ocr_mvp" if used_vision_ocr else "text_mvp",
                    "auto_approved": item_status == "approved",
                },
            )
            db.add(item)
            db.flush()
            saved.append(item)
        elif _enrich_existing_question_bank_item(item, draft):
            db.add(item)
        if item.status == "pending" and item_status == "approved":
            item.status = "approved"
            raw_item_meta = dict(item.raw_meta or {})
            raw_item_meta["auto_approved"] = True
            item.raw_meta = raw_item_meta
            db.add(item)
        source = (
            db.query(QuestionBankSource)
            .filter(
                QuestionBankSource.item_id == item.id,
                QuestionBankSource.paper_id == paper.id,
                QuestionBankSource.question_no == str(draft.get("question_no")),
            )
            .first()
        )
        if not source:
            db.add(
                QuestionBankSource(
                    item_id=item.id,
                    paper_id=paper.id,
                    question_no=str(draft.get("question_no")),
                    source_url=paper.source_url,
                    source_title=paper.title,
                    raw_text=str(draft.get("raw_text", ""))[:2000],
                )
            )
    raw_meta = dict(paper.raw_meta or {})
    raw_meta["parse"] = {
        "parsed_count": len(drafts),
        "saved_count": len(saved),
        "parser": "vision_ocr_mvp" if used_vision_ocr else "text_mvp",
        "used_vision_ocr": used_vision_ocr,
    }
    paper.raw_meta = raw_meta
    db.add(paper)
    db.commit()
    for item in saved:
        db.refresh(item)
    if missing_answer_count:
        warnings.append(f"{missing_answer_count} 道题缺少答案，已保持 pending，未自动进入正式组卷池")
    return ParsePaperSourceResponse(
        paper_id=paper.id,
        parsed_count=len(drafts),
        saved_count=len(saved),
        items=[_to_bank_item(item) for item in saved],
        warnings=warnings,
    )


async def search_and_save_paper_sources(
    db: Session, req: SearchPaperSourcesRequest, created_by: int | None = None
) -> tuple[list[str], list[QuestionBankPaper]]:
    queries, candidates = await search_service.search_public_paper_candidates(req)
    return queries, save_paper_candidates(db, req, candidates, created_by)


def to_item(paper: QuestionBankPaper) -> QuestionBankPaperItem:
    raw_meta = paper.raw_meta or {}
    return QuestionBankPaperItem(
        id=paper.id,
        title=paper.title,
        source_url=paper.source_url,
        snippet=paper.snippet,
        province=paper.province,
        city=paper.city,
        district=paper.district,
        school=paper.school,
        grade=paper.grade,
        semester=paper.semester,
        subject=paper.subject,
        textbook_version=paper.textbook_version,
        year=paper.year,
        exam_type=paper.exam_type,
        source_type=paper.source_type,
        availability_level=paper.availability_level,
        risk_level=paper.risk_level,
        status=paper.status,
        confidence=paper.confidence,
        source_adapter=raw_meta.get("source_adapter"),
        review=raw_meta.get("review"),
    )
