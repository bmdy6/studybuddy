from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, resolve_accessible_student_id
from app.models.user import User
from .retrieval import search_workspace_memory
from .relations import create_relations, list_relations
from .schemas import RelationIn

router = APIRouter(prefix="/api/memory", tags=["memory"])

@router.get("/search")
def api_search(q: str = Query(""), student_id: int | None = None, k: int = 8, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = resolve_accessible_student_id(db, user, student_id)
    return search_workspace_memory(db, sid, q, k=k)

@router.post("/relations")
def api_create_relations(items: list[RelationIn], student_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = resolve_accessible_student_id(db, user, student_id)
    rows = create_relations(db, sid, [i.model_dump() for i in items])
    return rows

@router.get("/relations")
def api_list_relations(student_id: int | None = None, source_type: str | None = None, source_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = resolve_accessible_student_id(db, user, student_id)
    return list_relations(db, sid, source_type, source_id)
