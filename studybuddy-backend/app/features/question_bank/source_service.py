"""试卷来源 CRUD + 审核（从 question_bank_service 拆出，技术债中6）。"""

from __future__ import annotations



from datetime import datetime
from typing import Any
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.models.question_bank import QuestionBankPaper
from .schemas import CreatePaperSourceRequest, PaperSourceFullPreviewResponse, QuestionBankReviewBreakdown, QuestionBankReviewMetrics, QuestionBankPaperReview


from .parsers import _clean_text, _estimate_question_count, _extract_visible_text, _looks_like_pdf
from .scoring import _classify_candidate, _hash_url
from .upload_service import _extract_pdf_text


_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_PREVIEW_SIGNALS = ("预览", "部分内容", "阅读全文", "继续阅读", "仅展示", "剩余", "下载后查看")
_ACCESS_BLOCK_SIGNALS = ("登录", "注册", "付费", "vip", "购买", "充值", "权限", "验证码", "网盘提取码")
_ANSWER_SIGNALS = ("答案", "参考答案", "答案解析", "解析", "answer", "参考解答")
_REVIEW_METRIC_MIN_SAMPLE_SIZE = 20
_MAX_FORMAL_READY_FALSE_POSITIVE_RATE = 0.1


def create_manual_paper_source(db: Session, req: CreatePaperSourceRequest, created_by: int | None = None) -> QuestionBankPaper:
    title = _clean_text(req.title)[:300]
    url = req.source_url.strip()
    snippet = _clean_text(req.snippet or "")
    source_type, availability, risk, confidence = _classify_candidate(title, url, snippet)
    if req.source_adapter in {"school_official", "education_bureau", "official_edu"} and availability != "C":
        availability = "A"
        risk = "low"
        if req.source_adapter == "school_official":
            source_type = "school_paper"
        elif req.source_adapter in {"education_bureau", "official_edu"}:
            source_type = "district_paper"
        confidence = max(confidence, 78)
    url_hash = _hash_url(url)
    existing = db.query(QuestionBankPaper).filter(QuestionBankPaper.source_url_hash == url_hash).first()
    raw_meta = {"query": "manual_entry", "source_adapter": req.source_adapter, "manual_entry": True}
    if existing:
        existing.title = title or existing.title
        existing.snippet = snippet or existing.snippet
        existing.province = req.province or existing.province
        existing.city = req.city or existing.city
        existing.district = req.district or existing.district
        existing.school = req.school or existing.school
        existing.grade = req.grade or existing.grade
        existing.semester = req.semester or existing.semester
        existing.subject = req.subject or existing.subject
        existing.textbook_version = req.textbook_version or existing.textbook_version
        existing.exam_type = req.exam_type or existing.exam_type
        existing.year = req.year or existing.year
        existing.source_type = source_type
        existing.availability_level = availability
        existing.risk_level = risk
        existing.confidence = confidence
        existing.raw_meta = {**(existing.raw_meta or {}), **raw_meta}
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    paper = QuestionBankPaper(
        title=title,
        source_url=url,
        source_url_hash=url_hash,
        snippet=snippet,
        province=req.province,
        city=req.city,
        district=req.district,
        school=req.school,
        grade=req.grade,
        semester=req.semester,
        subject=req.subject,
        textbook_version=req.textbook_version,
        year=req.year,
        exam_type=req.exam_type,
        source_type=source_type,
        availability_level=availability,
        risk_level=risk,
        status="internal_style" if availability == "C" else "candidate",
        confidence=confidence,
        created_by=created_by,
        raw_meta=raw_meta,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


def list_paper_sources(
    db: Session,
    *,
    status: str | None = None,
    grade: str | None = None,
    semester: str | None = None,
    subject: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> list[QuestionBankPaper]:
    query = db.query(QuestionBankPaper)
    if status:
        query = query.filter(QuestionBankPaper.status == status)
    if grade:
        query = query.filter(QuestionBankPaper.grade == grade)
    if semester:
        query = query.filter(QuestionBankPaper.semester == semester)
    if subject:
        query = query.filter(QuestionBankPaper.subject == subject)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(QuestionBankPaper.title.like(like))
    return query.order_by(QuestionBankPaper.confidence.desc(), QuestionBankPaper.id.desc()).limit(limit).all()


def update_paper_source_status(db: Session, paper_id: int, status: str) -> QuestionBankPaper | None:
    paper = db.get(QuestionBankPaper, paper_id)
    if not paper:
        return None
    paper.status = status
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


def _suggested_status_from_review(review: dict[str, Any]) -> str:
    suggested = str(review.get("suggested_status") or "")
    if suggested:
        return suggested
    verdict = str(review.get("verdict") or "")
    return {
        "formal_ready": "confirmed",
        "style_only": "internal_style",
        "reject": "rejected",
        "needs_manual": "candidate",
    }.get(verdict, "candidate")


def get_review_metrics(db: Session) -> QuestionBankReviewMetrics:
    papers = db.query(QuestionBankPaper).all()
    total_reviewed = 0
    sampled_count = 0
    agreement_count = 0
    formal_ready_sampled_count = 0
    formal_ready_false_positive_count = 0
    reject_sampled_count = 0
    reject_false_negative_count = 0
    breakdown: dict[str, dict[str, int]] = {}

    for paper in papers:
        raw_meta = paper.raw_meta or {}
        review = raw_meta.get("review")
        if not isinstance(review, dict):
            continue
        total_reviewed += 1
        verdict = str(review.get("verdict") or "unknown")
        suggested_status = _suggested_status_from_review(review)
        bucket = breakdown.setdefault(
            verdict,
            {
                "total_count": 0,
                "sampled_count": 0,
                "agreement_count": 0,
                "confirmed_count": 0,
                "rejected_count": 0,
                "internal_style_count": 0,
                "candidate_count": 0,
            },
        )
        bucket["total_count"] += 1
        status_key = f"{paper.status}_count"
        if status_key in bucket:
            bucket[status_key] += 1

        if paper.status == "candidate":
            continue
        sampled_count += 1
        bucket["sampled_count"] += 1
        if suggested_status == paper.status:
            agreement_count += 1
            bucket["agreement_count"] += 1
        if suggested_status == "confirmed":
            formal_ready_sampled_count += 1
            if paper.status in {"rejected", "internal_style"}:
                formal_ready_false_positive_count += 1
        if suggested_status == "rejected":
            reject_sampled_count += 1
            if paper.status == "confirmed":
                reject_false_negative_count += 1

    agreement_rate = round(agreement_count / sampled_count, 4) if sampled_count else None
    formal_ready_false_positive_rate = (
        round(formal_ready_false_positive_count / formal_ready_sampled_count, 4)
        if formal_ready_sampled_count
        else None
    )
    reject_false_negative_rate = (
        round(reject_false_negative_count / reject_sampled_count, 4) if reject_sampled_count else None
    )
    has_enough_samples = sampled_count >= _REVIEW_METRIC_MIN_SAMPLE_SIZE
    has_formal_ready_samples = formal_ready_sampled_count > 0
    formal_ready_error_ok = (formal_ready_false_positive_rate or 0) <= _MAX_FORMAL_READY_FALSE_POSITIVE_RATE
    auto_approve_allowed = has_enough_samples and has_formal_ready_samples and formal_ready_error_ok
    return QuestionBankReviewMetrics(
        total_reviewed=total_reviewed,
        sampled_count=sampled_count,
        agreement_count=agreement_count,
        agreement_rate=agreement_rate,
        formal_ready_sampled_count=formal_ready_sampled_count,
        formal_ready_false_positive_count=formal_ready_false_positive_count,
        formal_ready_false_positive_rate=formal_ready_false_positive_rate,
        reject_sampled_count=reject_sampled_count,
        reject_false_negative_count=reject_false_negative_count,
        reject_false_negative_rate=reject_false_negative_rate,
        min_sample_size=_REVIEW_METRIC_MIN_SAMPLE_SIZE,
        max_formal_ready_false_positive_rate=_MAX_FORMAL_READY_FALSE_POSITIVE_RATE,
        auto_approve_allowed=auto_approve_allowed,
        verdict_breakdown=[
            QuestionBankReviewBreakdown(verdict=verdict, **counts)
            for verdict, counts in sorted(breakdown.items(), key=lambda item: item[0])
        ],
    )


def _auto_approval_decision(review: QuestionBankPaperReview, metrics: QuestionBankReviewMetrics) -> dict[str, Any]:
    if review.verdict != "formal_ready" or review.suggested_status != "confirmed":
        return {
            "applied": False,
            "target_status": "candidate",
            "reason": "AI 初审未达到 formal_ready/confirmed",
            "checked_at": review.checked_at,
        }
    if metrics.sampled_count < metrics.min_sample_size:
        return {
            "applied": False,
            "target_status": "candidate",
            "reason": f"人工标注样本量不足：{metrics.sampled_count}/{metrics.min_sample_size}",
            "checked_at": review.checked_at,
        }
    if metrics.formal_ready_sampled_count <= 0:
        return {
            "applied": False,
            "target_status": "candidate",
            "reason": "缺少 formal_ready 人工标注样本",
            "checked_at": review.checked_at,
        }
    if not metrics.auto_approve_allowed:
        rate = metrics.formal_ready_false_positive_rate
        return {
            "applied": False,
            "target_status": "candidate",
            "reason": "formal_ready 误判率超过门禁" if rate is not None else "formal_ready 误判率样本不足",
            "checked_at": review.checked_at,
        }
    return {
        "applied": True,
        "target_status": "confirmed",
        "reason": "AI 初审通过且人工样本质量门禁已通过",
        "checked_at": review.checked_at,
    }


async def fetch_paper_source_preview(paper: QuestionBankPaper) -> dict[str, str | int | bool]:
    """下载候选来源的轻量预览，用于完整性初审。

    不保存原文；只返回可审查证据，避免把外部试卷内容直接落库。
    """
    try:
        async with httpx.AsyncClient(timeout=settings.config.question_bank.review_timeout_seconds, headers={"User-Agent": _USER_AGENT}, follow_redirects=True) as client:
            resp = await client.get(paper.source_url)
            content_type = resp.headers.get("content-type", "")
            data = resp.content[:400_000]
            is_pdf = _looks_like_pdf(content_type, str(resp.url), data)
            if is_pdf:
                text = f"{paper.title} {paper.snippet or ''} PDF文件，大小约{len(resp.content)}字节"
            else:
                text = _extract_visible_text(data.decode(resp.encoding or "utf-8", errors="ignore"))
            return {
                "ok": resp.status_code < 400,
                "status_code": resp.status_code,
                "final_url": str(resp.url),
                "content_type": content_type,
                "is_pdf": is_pdf,
                "text": text[:12000],
                "content_length": len(resp.content),
                "content_bytes": data,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status_code": 0,
            "final_url": paper.source_url,
            "content_type": "",
            "is_pdf": False,
            "text": "",
            "content_length": 0,
            "error": str(exc),
        }


def _preview_response_from_text(
    paper: QuestionBankPaper,
    *,
    status: str,
    content_kind: str,
    message: str,
    text: str,
    final_url: str | None = None,
    warnings: list[str] | None = None,
) -> PaperSourceFullPreviewResponse:
    cleaned = _clean_text(text)
    question_count, last_question_no = _estimate_question_count(cleaned)
    has_answer = any(signal in cleaned.lower() for signal in _ANSWER_SIGNALS)
    return PaperSourceFullPreviewResponse(
        paper_id=paper.id,
        status=status,
        content_kind=content_kind,
        title=paper.title,
        message=message,
        source_url=paper.source_url,
        final_url=final_url,
        text=cleaned[:200_000] if cleaned else None,
        text_length=len(cleaned),
        question_count_estimate=question_count,
        last_question_no=last_question_no,
        has_answer_signal=has_answer,
        can_parse=status == "available" and bool(cleaned and question_count > 0),
        warnings=warnings or [],
    )


def _looks_like_login_or_blocked(final_url: str, text: str) -> bool:
    lower = f"{final_url} {text}".lower()
    return any(signal.lower() in lower for signal in _ACCESS_BLOCK_SIGNALS) or "smslogin" in lower or "/login" in lower


async def get_paper_source_full_preview(db: Session, paper_id: int) -> PaperSourceFullPreviewResponse | None:
    paper = db.get(QuestionBankPaper, paper_id)
    if not paper:
        return None

    uploaded_file = (paper.raw_meta or {}).get("uploaded_file") or {}
    uploaded_text = uploaded_file.get("extracted_text") if isinstance(uploaded_file, dict) else None
    if uploaded_text:
        return _preview_response_from_text(
            paper,
            status="available",
            content_kind="uploaded_text",
            message="已读取人工上传试卷的文本内容",
            text=str(uploaded_text),
            final_url=paper.source_url,
            warnings=["这是抽取文本预览，不是 PDF 原版排版"],
        )

    fetched = await fetch_paper_source_preview(paper)
    final_url = str(fetched.get("final_url") or paper.source_url)
    fetched_text = str(fetched.get("text") or "")
    if not fetched.get("ok"):
        return PaperSourceFullPreviewResponse(
            paper_id=paper.id,
            status="unreachable",
            content_kind="none",
            title=paper.title,
            message="来源不可访问，暂时无法获取整卷",
            source_url=paper.source_url,
            final_url=final_url,
            warnings=[str(fetched.get("error") or "来源不可访问")],
        )

    if _looks_like_login_or_blocked(final_url, fetched_text):
        return _preview_response_from_text(
            paper,
            status="login_required",
            content_kind="blocked_page",
            message="当前只拿到登录/权限页面，需要登录账号后才能下载整卷",
            text=fetched_text,
            final_url=final_url,
            warnings=["未拿到真实试卷文件，不能解析入正式题库"],
        )

    if fetched.get("is_pdf"):
        content_bytes = fetched.get("content_bytes")
        if not isinstance(content_bytes, bytes):
            return PaperSourceFullPreviewResponse(
                paper_id=paper.id,
                status="unavailable",
                content_kind="pdf",
                title=paper.title,
                message="检测到 PDF，但文件内容未下载成功",
                source_url=paper.source_url,
                final_url=final_url,
                warnings=["PDF 内容缺失，无法预览"],
            )
        try:
            pdf_text = _extract_pdf_text(content_bytes)
        except RuntimeError as exc:
            return PaperSourceFullPreviewResponse(
                paper_id=paper.id,
                status="unavailable",
                content_kind="pdf",
                title=paper.title,
                message="PDF 文本抽取失败",
                source_url=paper.source_url,
                final_url=final_url,
                warnings=[str(exc)],
            )
        return _preview_response_from_text(
            paper,
            status="available",
            content_kind="pdf_text",
            message="已下载公开 PDF 并抽取文本",
            text=pdf_text,
            final_url=final_url,
            warnings=["这是 PDF 抽取文本预览，不是原版排版"],
        )

    if fetched_text:
        return _preview_response_from_text(
            paper,
            status="available",
            content_kind="html_text",
            message="已读取网页正文文本",
            text=fetched_text,
            final_url=final_url,
            warnings=["网页正文可能只是预览页，解析前仍需看完整性"],
        )

    return PaperSourceFullPreviewResponse(
        paper_id=paper.id,
        status="unavailable",
        content_kind="none",
        title=paper.title,
        message="未获取到可预览的试卷正文",
        source_url=paper.source_url,
        final_url=final_url,
        warnings=["来源没有返回文本或可下载 PDF"],
    )


def review_paper_source_content(paper: QuestionBankPaper, fetched: dict[str, str | int | bool]) -> QuestionBankPaperReview:
    """基于抓取证据做自动初审，作为 AI 初审的可测试 MVP。"""
    text = f"{paper.title} {paper.snippet or ''} {fetched.get('text', '')}"
    text_lower = text.lower()
    reasons: list[str] = []
    evidence: dict[str, object] = {
        "status_code": fetched.get("status_code", 0),
        "final_url": fetched.get("final_url", paper.source_url),
        "content_type": fetched.get("content_type", ""),
        "is_pdf": bool(fetched.get("is_pdf")),
        "content_length": fetched.get("content_length", 0),
    }

    if not fetched.get("ok"):
        reasons.append("来源不可访问或下载失败")
        if fetched.get("error"):
            reasons.append(str(fetched["error"])[:120])
        return QuestionBankPaperReview(
            verdict="needs_manual",
            confidence=25,
            completeness="unreachable",
            suggested_status="candidate",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    question_count, last_question_no = _estimate_question_count(text)
    has_answer = any(signal in text_lower for signal in _ANSWER_SIGNALS)
    preview_signals = [signal for signal in _PREVIEW_SIGNALS if signal.lower() in text_lower]
    block_signals = [signal for signal in _ACCESS_BLOCK_SIGNALS if signal.lower() in text_lower]
    metadata_hits = {
        "grade": bool(paper.grade and paper.grade.lower() in text_lower),
        "subject": bool(paper.subject and paper.subject.lower() in text_lower),
        "district": bool(paper.district and paper.district.lower() in text_lower),
        "school": bool(paper.school and paper.school.lower() in text_lower),
        "exam_type": bool(paper.exam_type and paper.exam_type.lower() in text_lower),
    }
    evidence.update(
        {
            "question_count_estimate": question_count,
            "last_question_no": last_question_no,
            "has_answer_signal": has_answer,
            "preview_signals": preview_signals,
            "access_block_signals": block_signals,
            "metadata_hits": metadata_hits,
        }
    )

    if block_signals or paper.risk_level == "high":
        reasons.append("存在登录、付费、VIP 或高风险来源信号")
        return QuestionBankPaperReview(
            verdict="style_only",
            confidence=62,
            completeness="blocked_or_paid",
            suggested_status="internal_style",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if "duckduckgo.com/?q=" in paper.source_url or paper.source_type == "search_result":
        reasons.append("来源只是搜索入口，不是试卷正文")
        return QuestionBankPaperReview(
            verdict="needs_manual",
            confidence=45,
            completeness="search_result",
            suggested_status="candidate",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if preview_signals and question_count < 8:
        reasons.append("疑似只展示预览内容或前几题")
        return QuestionBankPaperReview(
            verdict="needs_manual",
            confidence=70,
            completeness="preview_only",
            suggested_status="candidate",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if bool(fetched.get("is_pdf")) and has_answer and paper.availability_level in {"A", "B"}:
        reasons.append("PDF 来源且标题/摘要包含答案信号，可优先进入解析队列")
        return QuestionBankPaperReview(
            verdict="formal_ready",
            confidence=max(70, min(92, paper.confidence)),
            completeness="likely_full",
            suggested_status="confirmed",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if question_count >= 12 and has_answer:
        reasons.append("页面识别到较多题号且包含答案/解析信号")
        return QuestionBankPaperReview(
            verdict="formal_ready",
            confidence=max(68, min(90, paper.confidence)),
            completeness="likely_full",
            suggested_status="confirmed",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if question_count >= 6:
        reasons.append("可看到部分题目，但答案或卷末证据不足")
        return QuestionBankPaperReview(
            verdict="needs_manual",
            confidence=60,
            completeness="partial",
            suggested_status="candidate",
            evidence=evidence,
            reasons=reasons,
            checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    reasons.append("未识别到足够题目正文")
    return QuestionBankPaperReview(
        verdict="reject",
        confidence=72,
        completeness="no_questions",
        suggested_status="rejected",
        evidence=evidence,
        reasons=reasons,
        checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


async def review_paper_source(db: Session, paper_id: int) -> QuestionBankPaper | None:
    paper = db.get(QuestionBankPaper, paper_id)
    if not paper:
        return None
    fetched = await fetch_paper_source_preview(paper)
    review = review_paper_source_content(paper, fetched)
    raw_meta = dict(paper.raw_meta or {})
    raw_meta["review"] = review.model_dump()
    decision = _auto_approval_decision(review, get_review_metrics(db))
    raw_meta["auto_approval"] = decision
    if decision["applied"]:
        paper.status = str(decision["target_status"])
    paper.raw_meta = raw_meta
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper
