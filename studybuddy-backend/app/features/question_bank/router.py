from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_teacher
from app.models.user import User
from .schemas import (
    CreatePaperSourceRequest,
    PaperSourceFullPreviewResponse,
    QuestionBankPaperItem,
    ParsePaperSourceResponse,
    QuestionBankItem,
    QuestionBankReviewMetrics,
    ReviewPaperSourceRequest,
    SearchPaperSourcesRequest,
    SearchPaperSourcesResponse,
    UpdateQuestionBankItemRequest,
    UpdatePaperSourceRequest,
    UploadedPaperSourceResponse,
    ValidateUploadedPaperFileResponse,
)
from . import service as question_bank_service

router = APIRouter(prefix="/api/question-bank", tags=["question-bank"])


@router.post("/paper-sources/search", response_model=SearchPaperSourcesResponse)
async def api_search_paper_sources(
    req: SearchPaperSourcesRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> SearchPaperSourcesResponse:
    queries, papers = await question_bank_service.search_and_save_paper_sources(db, req, created_by=user.id)
    return SearchPaperSourcesResponse(
        queries=queries,
        saved_count=len(papers),
        candidates=[question_bank_service.to_item(p) for p in papers],
    )


@router.post("/paper-sources", response_model=QuestionBankPaperItem)
def api_create_paper_source(
    req: CreatePaperSourceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> QuestionBankPaperItem:
    """人工录入学校官网/教育局/公开 PDF 等来源，进入候选库。"""
    paper = question_bank_service.create_manual_paper_source(db, req, created_by=user.id)
    return question_bank_service.to_item(paper)


@router.post("/paper-sources/validate-upload", response_model=ValidateUploadedPaperFileResponse)
async def api_validate_uploaded_paper_file(
    file: UploadFile = File(...),
    user: User = Depends(require_teacher),
) -> ValidateUploadedPaperFileResponse:
    """校验人工上传的试卷文件是否适合进入题库解析，不写入正式题库。"""
    _ = user
    data = await file.read()
    return question_bank_service.validate_uploaded_paper_file(file.filename or "upload", file.content_type, data)


@router.post("/paper-sources/upload", response_model=UploadedPaperSourceResponse)
async def api_upload_paper_source(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    grade: str = Form(...),
    subject: str = Form(...),
    province: str | None = Form(default=None),
    city: str | None = Form(default=None),
    district: str | None = Form(default=None),
    school: str | None = Form(default=None),
    semester: str | None = Form(default=None),
    textbook_version: str | None = Form(default=None),
    exam_type: str | None = Form(default=None),
    year: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> UploadedPaperSourceResponse:
    """把人工上传且可解析的试卷文件写入候选来源池，后续复用 parse 进入 pending 题库。"""
    data = await file.read()
    try:
        paper, validation = question_bank_service.create_uploaded_paper_source(
            db,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=data,
            title=title,
            grade=grade,
            subject=subject,
            province=province,
            city=city,
            district=district,
            school=school,
            semester=semester,
            textbook_version=textbook_version,
            exam_type=exam_type,
            year=year,
            created_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UploadedPaperSourceResponse(paper=question_bank_service.to_item(paper), validation=validation)


@router.get("/paper-sources", response_model=list[QuestionBankPaperItem])
def api_list_paper_sources(
    status: str | None = Query(default=None),
    grade: str | None = Query(default=None),
    semester: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> list[QuestionBankPaperItem]:
    papers = question_bank_service.list_paper_sources(
        db,
        status=status,
        grade=grade,
        semester=semester,
        subject=subject,
        keyword=keyword,
        limit=limit,
    )
    return [question_bank_service.to_item(p) for p in papers]


@router.patch("/paper-sources/{paper_id}", response_model=QuestionBankPaperItem)
def api_update_paper_source(
    paper_id: int,
    req: UpdatePaperSourceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> QuestionBankPaperItem:
    paper = question_bank_service.update_paper_source_status(db, paper_id, req.status)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷候选不存在")
    return question_bank_service.to_item(paper)


@router.get("/review-metrics", response_model=QuestionBankReviewMetrics)
def api_get_review_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> QuestionBankReviewMetrics:
    """AI 初审与人工抽样结果的准确率统计。"""
    _ = user
    return question_bank_service.get_review_metrics(db)


@router.post("/paper-sources/{paper_id}/review", response_model=QuestionBankPaperItem)
async def api_review_paper_source(
    paper_id: int,
    req: ReviewPaperSourceRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> QuestionBankPaperItem:
    """完整性/AI 初审：抓取来源，记录证据和建议结论，不自动入正式题库。"""
    _ = req
    paper = await question_bank_service.review_paper_source(db, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷候选不存在")
    return question_bank_service.to_item(paper)


@router.post("/paper-sources/{paper_id}/parse", response_model=ParsePaperSourceResponse)
async def api_parse_paper_source(
    paper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> ParsePaperSourceResponse:
    """把完整性通过的网页来源解析为项目级待确认题目。"""
    result = await question_bank_service.parse_paper_source_to_items(db, paper_id)
    if not result:
        raise HTTPException(status_code=404, detail="试卷候选不存在")
    return result


@router.get("/paper-sources/{paper_id}/full-preview", response_model=PaperSourceFullPreviewResponse)
async def api_get_paper_source_full_preview(
    paper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> PaperSourceFullPreviewResponse:
    """查看候选来源当前能拿到的整卷内容；需要登录/权限时返回明确状态。"""
    _ = user
    result = await question_bank_service.get_paper_source_full_preview(db, paper_id)
    if not result:
        raise HTTPException(status_code=404, detail="试卷候选不存在")
    return result


@router.get("/items", response_model=list[QuestionBankItem])
def api_list_question_bank_items(
    status: str | None = Query(default="pending"),
    subject: str | None = Query(default=None),
    grade: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> list[QuestionBankItem]:
    """查询项目级题库题目，用于人工审核 pending 题。"""
    _ = user
    return question_bank_service.list_question_bank_items(
        db,
        status=status,
        subject=subject,
        grade=grade,
        keyword=keyword,
        limit=limit,
    )


@router.patch("/items/{item_id}", response_model=QuestionBankItem)
def api_update_question_bank_item(
    item_id: int,
    req: UpdateQuestionBankItemRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher),
) -> QuestionBankItem:
    """人工确认题目是否进入正式组卷池。"""
    _ = user
    item = question_bank_service.update_question_bank_item_status(db, item_id, req.status)
    if not item:
        raise HTTPException(status_code=404, detail="题库题目不存在")
    return item
