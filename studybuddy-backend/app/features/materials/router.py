import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.constants import ALLOWED_MATERIAL_EXTENSIONS
from app.database import get_db
from app.deps import get_current_user
from app.models.material import Material
from app.models.user import User
from .schemas import (
    MaterialExtractionConfirmRequest,
    MaterialExtractionResponse,
    MaterialItem,
    MaterialUploadResponse,
)
from .extraction_service import (
    MaterialRecognitionPreconditionError,
    confirm_material_extraction,
    get_material_extraction,
    recognize_material,
)
from .service import (
    MaterialOwnerForbiddenError,
    build_preview_info,
    can_access_material,
    delete_material,
    list_materials,
    upload_material_async,
)

router = APIRouter(prefix="/api/material", tags=["material"])


def ensure_material_access(db: Session, material: Material, user: User) -> None:
    """校验当前用户是否可访问素材。"""
    if can_access_material(db, material, user):
        return
    raise HTTPException(status_code=403, detail="无权访问该素材")


def parse_knowledge_tags(raw_tags: str) -> list[str]:
    """解析素材知识点标签表单字段，返回去重后的字符串列表。"""
    if not raw_tags:
        return []
    try:
        parsed = json.loads(raw_tags)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail="knowledge_tags 必须是 JSON 字符串数组") from e
    if not isinstance(parsed, list) or any(not isinstance(tag, str) for tag in parsed):
        raise HTTPException(status_code=422, detail="knowledge_tags 必须是 JSON 字符串数组")

    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in parsed:
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


@router.post("/upload", response_model=MaterialUploadResponse, status_code=201)
async def api_upload(
    file: UploadFile = File(...),
    name: str = Form(...),
    type: str = Form(...),
    knowledge_tags: str = Form("[]"),
    target_student_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialUploadResponse:
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_MATERIAL_EXTENSIONS:
        allowed = "、".join(sorted(ALLOWED_MATERIAL_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"仅支持上传素材格式：{allowed}")
    tags = parse_knowledge_tags(knowledge_tags)
    file_bytes = await file.read()
    try:
        return await upload_material_async(db, file_bytes, ext, name, type, tags, user, target_student_id)
    except MaterialOwnerForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("", response_model=list[MaterialItem])
def api_list(
    source: str | None = None,
    type: str | None = None,
    include_duplicates: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MaterialItem]:
    # 素材：学生看自己模式的；家长管理视角看全部（不按模式过滤）
    mode_for_query = user.mode if user.role == "student" else None
    return list_materials(db, user, source, type, include_duplicates=include_duplicates, mode=mode_for_query)


@router.get("/{material_id}/preview-url")
def api_preview_url(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回素材的可预览 URL + 文件扩展名，前端据此选择预览方式。

    本地存储模式直接返回 StaticFiles 路径；COS 模式返回公开/签名 URL。
    """
    m = db.get(Material, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="素材不存在")
    ensure_material_access(db, m, user)

    return build_preview_info(m)


@router.delete("/{material_id}", status_code=204)
def api_delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除素材：学生只能删自己的，老师可删任意。"""
    try:
        delete_material(db, material_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{material_id}/recognize", response_model=MaterialExtractionResponse)
async def api_recognize_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialExtractionResponse:
    try:
        return await recognize_material(db, material_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except MaterialRecognitionPreconditionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{material_id}/extraction", response_model=MaterialExtractionResponse)
def api_get_material_extraction(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialExtractionResponse:
    try:
        return get_material_extraction(db, material_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{material_id}/extraction/confirm", response_model=MaterialExtractionResponse)
def api_confirm_material_extraction(
    material_id: int,
    payload: MaterialExtractionConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialExtractionResponse:
    try:
        return confirm_material_extraction(db, material_id, payload.confirmed_markdown, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except MaterialRecognitionPreconditionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
# agg-1
