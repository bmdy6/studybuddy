"""考试批次路由：错题导入。

阶段一：POST /api/exam-batches 建批次 + POST /api/exam-batches/{id}/photos 批量上传照片
阶段二：POST /api/exam-batches/{id}/synthesize 合成PDF + POST /api/exam-batches/{id}/parse 视觉解析
阶段三：判分入错题本（后续）
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.constants import ALLOWED_EXAM_PHOTO_EXTENSIONS
from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.exam_batch import ExamBatch
from app.models.user import User
from .schemas.exam_batch import (
    BatchItem,
    ConfirmAnswerReviewRequest,
    CreateBatchRequest,
    GradeBatchRequest,
    ParseResult,
    PhotoAnswerReviewState,
)
from . import batch_service as exam_batch_service

router = APIRouter(prefix="/api/exam-batches", tags=["exam-batches"])


@router.post("", response_model=BatchItem, status_code=201)
def api_create_batch(
    req: CreateBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchItem:
    """创建考试批次。"""
    sid = resolve_accessible_student_id(db, user, req.student_id) if user.role == "teacher" else user.id
    return exam_batch_service.create_batch(db, sid, req.subject, req.exam_name, req.exam_date)


@router.get("", response_model=list[BatchItem])
def api_list_batches(
    student_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BatchItem]:
    """列批次。student 查自己的，teacher 指定 student_id。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    return exam_batch_service.list_batches(db, sid)


@router.post("/{batch_id}/photos", response_model=BatchItem)
async def api_upload_photos(
    batch_id: int,
    files: list[UploadFile] = File(...),
    page_type: str = Form("试卷"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchItem:
    """批量上传照片到批次（存子文件夹+重命名+进素材库）。"""
    batch = _get_accessible_batch(db, batch_id, user)
    for f in files:
        _validate_photo_filename(f.filename or "photo.jpg")
        data = await f.read()
        exam_batch_service.save_photo_to_batch(db, batch, f.filename or "photo.jpg", data, user.id, page_type)
    return exam_batch_service.to_item(batch)


@router.delete("/{batch_id}", status_code=204)
def api_delete_empty_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """清理上传失败留下的空批次。已有照片/解析结果的批次不能删除。"""
    batch = _get_accessible_batch(db, batch_id, user)
    if not exam_batch_service.delete_empty_batch(db, batch):
        raise HTTPException(status_code=409, detail="只能删除尚未上传照片的空批次")


@router.post("/{batch_id}/synthesize")
def api_synthesize(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """img2pdf 合成 PDF（留档预览）。"""
    batch = _get_accessible_batch(db, batch_id, user)
    ref = exam_batch_service.synthesize_pdf(db, batch)
    return {"pdf_ref": ref, "saved": bool(ref)}


@router.post("/{batch_id}/parse", response_model=ParseResult)
async def api_parse(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ParseResult:
    """MiMo 视觉解析批次照片，返回每题作答。"""
    batch = _get_accessible_batch(db, batch_id, user)
    return await exam_batch_service.parse_photos_and_mark_parsed(db, batch)


@router.get("/{batch_id}/answer-review", response_model=PhotoAnswerReviewState)
def api_get_answer_review(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PhotoAnswerReviewState:
    """读取拍题逐题作答核对状态。"""
    batch = _get_accessible_batch(db, batch_id, user)
    state = exam_batch_service.get_answer_review_state(batch)
    if not state:
        raise HTTPException(status_code=404, detail="该批次还没有可核对的拍题作答")
    return state


@router.post("/{batch_id}/answer-review/confirm", response_model=PhotoAnswerReviewState)
def api_confirm_answer_review(
    batch_id: int,
    req: ConfirmAnswerReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PhotoAnswerReviewState:
    """确认或修正拍题识别出的逐题作答。"""
    batch = _get_accessible_batch(db, batch_id, user)
    try:
        return exam_batch_service.confirm_answer_review(db, batch, req.items)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{batch_id}/grade")
async def api_grade(
    batch_id: int,
    req: GradeBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """阶段三：判分 + 入错题本。

    body:
      grade_mode: has_score / no_score_has_answer / no_score_no_answer
      manual_scores: {题号: 分数}（has_score 模式）
      standard_answers: {题号: 标准答案}（no_score_has_answer 模式）
      parsed_questions: [{no,answer,score}] 可选，不传则重新解析
    """
    batch = _get_accessible_batch(db, batch_id, user)

    # 没传 parsed_questions 就重新解析
    parsed = req.parsed_questions
    if not parsed:
        result = await exam_batch_service.parse_photos_with_vision(db, batch)
        parsed = result.questions

    return exam_batch_service.grade_and_save_errors(
        db,
        batch,
        parsed,
        req.grade_mode,
        req.manual_scores,
        req.standard_answers,
    )


def _get_accessible_batch(db: Session, batch_id: int, user: User) -> ExamBatch:
    """读取批次并校验当前用户是否可访问该批次学生。"""
    batch = exam_batch_service.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    resolve_accessible_student_id(db, user, batch.student_id)
    return batch


def _validate_photo_filename(filename: str) -> None:
    """校验错题导入照片扩展名。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXAM_PHOTO_EXTENSIONS:
        allowed = "、".join(sorted(ALLOWED_EXAM_PHOTO_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"仅支持上传照片格式：{allowed}")
