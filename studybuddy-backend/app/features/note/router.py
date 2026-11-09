"""笔记路由：学习记录 CRUD + 盲区聚合。

权限：student 管自己的笔记（增删改查），parent 只读查弟弟笔记。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.note import Note
from app.models.user import User
from .schemas import BlindSpotItem, CreateNoteRequest, NoteItem, UpdateNoteRequest
from . import service as note_service

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[NoteItem])
def api_list(
    student_id: int | None = None,
    subject: str | None = None,
    type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NoteItem]:
    """列笔记。student 只看自己的；parent 指定 student_id 看弟弟的。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    student = db.get(User, sid)
    student_mode = getattr(student, "mode", "study") if student else "study"
    return note_service.list_notes(db, sid, subject, type, mode=student_mode)


@router.post("", response_model=NoteItem, status_code=201)
def api_create(
    req: CreateNoteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteItem:
    """创建笔记（agent save_note 工具调，或前端弟弟手动建）。"""
    sid = resolve_accessible_student_id(db, user, req.student_id) if user.role == "teacher" else user.id
    student = db.get(User, sid)
    student_mode = getattr(student, "mode", "study") if student else "study"
    data = req.model_dump()
    data["student_id"] = sid
    return note_service.create_note(db, data, mode=student_mode)


@router.get("/blind-spots", response_model=list[BlindSpotItem])
def api_blind_spots(
    student_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BlindSpotItem]:
    """盲区聚合：高频错题知识点 + 关联笔记数。"""
    sid = resolve_accessible_student_id(db, user, student_id)
    return note_service.get_blind_spots(db, sid)


def _ensure_note_access(db: Session, user: User, student_id: int) -> None:
    """校验当前用户是否可访问某篇笔记所属学生。"""
    resolve_accessible_student_id(db, user, student_id)


@router.get("/{note_id}", response_model=NoteItem)
def api_get(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteItem:
    item = note_service.get_note(db, note_id)
    if not item:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _ensure_note_access(db, user, item.student_id)
    return item


@router.get("/{note_id}/related-errors")
def api_related_errors(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """笔记关联的错题（按 knowledge_tags 匹配）。家长/学生都可查。"""
    n = db.get(Note, note_id)
    if not n:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _ensure_note_access(db, user, n.student_id)
    return note_service.get_related_errors(db, n)


@router.patch("/{note_id}", response_model=NoteItem)
def api_update(
    note_id: int,
    req: UpdateNoteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteItem:
    """更新笔记。parent 无权改（只读）。"""
    if user.role == "teacher":
        raise HTTPException(status_code=403, detail="家长只读，不可编辑")
    existing = db.get(Note, note_id)
    if not existing:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _ensure_note_access(db, user, existing.student_id)
    data = req.model_dump(exclude_none=True)
    item = note_service.update_note(db, note_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return item


@router.delete("/{note_id}", status_code=204)
def api_delete(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除笔记。parent 无权删（只读）。"""
    if user.role == "teacher":
        raise HTTPException(status_code=403, detail="家长只读，不可删除")
    existing = db.get(Note, note_id)
    if not existing:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _ensure_note_access(db, user, existing.student_id)
    if not note_service.delete_note(db, note_id):
        raise HTTPException(status_code=404, detail="笔记不存在")
