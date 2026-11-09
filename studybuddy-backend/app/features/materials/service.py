"""素材上传、归属、去重、访问边界与列表服务（spec 第四/五/八章）。

注意：knowledge_tags 为 JSON 列，直接传 list，不要 json.dumps。
"""

import asyncio
import hashlib
import logging
import os

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.material import Material
from app.models.user import User
from app.core.auth import access_service
from app.utils.cos import build_public_url as _build_url
from app.utils.cos import normalize_local_content_ref, upload_file

from .schemas import MaterialItem, MaterialUploadResponse

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class MaterialOwnerForbiddenError(PermissionError):
    """家长上传时 target_student_id 未绑定，归属解析失败。"""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _to_upload_response(material: Material, cos_key: str, user: User) -> MaterialUploadResponse:
    """把素材 ORM 对象转换为上传响应。"""
    return MaterialUploadResponse(
        material_id=material.id,
        name=material.name,
        type=material.type,
        source=material.source,
        cos_key=cos_key,
        uploaded_by=user.display_name or user.username,
        created_at=material.created_at.isoformat() if material.created_at else "",
        is_duplicate=False,
        duplicate_of_material_id=None,
        student_id=material.student_id,
    )


def resolve_material_owner(db: Session, user: User, target_student_id: int | None) -> int | None:
    """解析素材真实归属学生 id（spec 第四章）。

    - 学生上传：忽略 target_student_id，owner = user.id（学生自己）。
    - 家长上传且传 target_student_id：校验绑定关系，通过则 owner = target_student_id；不通过 403。
    - 家长上传未传 target_student_id：owner = None（归属未定，去重 fallback uploaded_by）。

    返回 None 表示归属未定（写入 student_id=NULL）。
    """
    if user.role == "student":
        return user.id
    # 家长上传
    if target_student_id is None:
        return None
    if not access_service.teacher_can_access_student(db, user.id, target_student_id):
        raise MaterialOwnerForbiddenError("家长未绑定该学生，无权为其上传素材")
    return target_student_id


def _find_existing_by_sha(db: Session, owner: int | None, user: User, file_sha256: str) -> Material | None:
    """在归属范围内按 file_sha256 查已有素材（spec 5.1）。

    - owner 非 NULL：WHERE student_id == owner AND file_sha256 == sha
    - owner NULL：WHERE student_id IS NULL AND uploaded_by == user.id AND file_sha256 == sha
    跨学生同文件不拦截（不同 owner）；旧数据 file_sha256=NULL 不参与命中。
    """
    if owner is not None:
        return (
            db.query(Material)
            .filter(Material.student_id == owner, Material.file_sha256 == file_sha256)
            .order_by(Material.id.asc())
            .first()
        )
    return (
        db.query(Material)
        .filter(
            Material.student_id.is_(None),
            Material.uploaded_by == user.id,
            Material.file_sha256 == file_sha256,
        )
        .order_by(Material.id.asc())
        .first()
    )


def _create_material_record(
    db: Session,
    cos_key: str,
    name: str,
    mtype: str,
    knowledge_tags: list[str],
    user: User,
    student_id: int | None,
    file_sha256: str | None,
) -> Material:
    """创建素材落库记录并返回 ORM 对象。"""
    # 素材归属=目标学生，mode 按归属学生的模式落（家长上传给学生时也用学生的模式）
    owner_id = student_id or user.id
    owner = db.get(User, owner_id)
    material_mode = getattr(owner, "mode", "study") if owner else "study"
    material = Material(
        name=name,
        type=mtype,
        source=user.role,  # teacher 或 student
        content_ref=cos_key,
        knowledge_tags=knowledge_tags,  # JSON 列，直接传 list
        uploaded_by=user.id,
        student_id=student_id,
        file_sha256=file_sha256,
        mode=material_mode,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def upload_material(
    db: Session,
    file_bytes: bytes,
    ext: str,
    name: str,
    mtype: str,
    knowledge_tags: list[str],
    user: User,
    target_student_id: int | None = None,
) -> MaterialUploadResponse:
    """上传素材 -> 文件层去重 -> 落库 -> 自动识别。

    fail-closed：COS 失败抛异常，不落库。
    命中同归属范围同 SHA-256 -> 返回已有素材（is_duplicate=True），不新建、不重复上传。
    """
    file_sha256 = _sha256_hex(file_bytes)
    owner = resolve_material_owner(db, user, target_student_id)
    existing = _find_existing_by_sha(db, owner, user, file_sha256)
    if existing is not None:
        resp = _to_upload_response(existing, existing.content_ref or "", user)
        resp.is_duplicate = True
        resp.duplicate_of_material_id = existing.id
        return resp

    cos_key = upload_file(file_bytes, ext)  # 失败抛 RuntimeError，不落库
    material = _create_material_record(db, cos_key, name, mtype, knowledge_tags, user, owner, file_sha256)
    # 同步入口仅做上传+去重+落库；识别懒触发，由 read_material 首次读取时调 ensure_extraction。
    return _to_upload_response(material, cos_key, user)


async def upload_material_async(
    db: Session,
    file_bytes: bytes,
    ext: str,
    name: str,
    mtype: str,
    knowledge_tags: list[str],
    user: User,
    target_student_id: int | None = None,
) -> MaterialUploadResponse:
    """在线程池上传素材文件，避免阻塞 FastAPI 事件循环。

    上传 -> 文件层去重 -> 落库。不在此处识别：识别改为懒触发，
    Agent 首次 read_material 时调 ensure_extraction 转成 Markdown 并缓存。
    避免上传同步识别卡死（非图片留 pending、图片 worker 超时留 processing）。
    """
    file_sha256 = _sha256_hex(file_bytes)
    owner = resolve_material_owner(db, user, target_student_id)
    existing = _find_existing_by_sha(db, owner, user, file_sha256)
    if existing is not None:
        resp = _to_upload_response(existing, existing.content_ref or "", user)
        resp.is_duplicate = True
        resp.duplicate_of_material_id = existing.id
        return resp

    cos_key = await asyncio.to_thread(upload_file, file_bytes, ext)  # 失败抛 RuntimeError，不落库
    material = _create_material_record(db, cos_key, name, mtype, knowledge_tags, user, owner, file_sha256)
    # 不触发识别：状态保持 pending，前端渲染为「已上传·可用」；Agent 首次读取时懒识别。
    return _to_upload_response(material, cos_key, user)


def build_local_upload_path(content_ref: str) -> str:
    """把本地素材 content_ref 转为 uploads 目录下的绝对路径。"""
    return os.path.join(_PROJECT_ROOT, "uploads", normalize_local_content_ref(content_ref))


def build_preview_info(material: Material) -> dict[str, str]:
    """构造素材预览信息，隐藏 content_ref 到 URL 的具体规则。"""
    content_ref = material.content_ref or ""
    ext = content_ref.rsplit(".", 1)[-1].lower() if "." in content_ref else ""
    return {"url": _build_url(content_ref), "ext": ext, "name": material.name}


def can_access_material(db: Session, material: Material, user: User) -> bool:
    """素材访问边界：优先按真实归属学生，旧数据才回退上传者。"""
    if material.student_id is not None:
        if user.role == "student":
            return material.student_id == user.id
        return access_service.teacher_can_access_student(db, user.id, material.student_id)

    if material.uploaded_by == user.id:
        return True
    if user.role == "student":
        return False
    uploader = db.get(User, material.uploaded_by)
    return bool(uploader and uploader.role == "student" and access_service.teacher_can_access_student(db, user.id, uploader.id))


def delete_material(db: Session, material_id: int, user: User) -> None:
    """删素材：只能删除自己或绑定学生上传的素材。本地文件尽力删不阻塞。"""
    m = db.get(Material, material_id)
    if not m:
        raise ValueError("素材不存在")
    if not can_access_material(db, m, user):
        raise PermissionError("无权删除该素材")
    # 本地文件尽力删（COS 对象暂不删，留档；失败不阻塞删库）
    if m.content_ref and m.content_ref.startswith("local:"):
        local_path = build_local_upload_path(m.content_ref)
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except OSError:
            pass  # 文件删失败不阻塞，DB 删掉即可
    db.delete(m)
    db.commit()


def list_materials(
    db: Session,
    user: User,
    source: str | None = None,
    mtype: str | None = None,
    include_duplicates: bool = False,
    mode: str | None = None,
) -> list[MaterialItem]:
    """列素材：学生看自己的归属素材（按自己模式），家长看绑定学生素材（全部模式）。

    默认排除 duplicate_of_material_id 非空的素材（归一展示，spec 8.1）。
    include_duplicates=True 显示全部。
    """
    query = db.query(Material, User).join(User, Material.uploaded_by == User.id)
    if mode is not None:
        query = query.filter(Material.mode == mode)
    if user.role == "student":
        query = query.filter(
            or_(
                Material.student_id == user.id,
                and_(Material.student_id.is_(None), Material.uploaded_by == user.id),
            )
        )
    else:
        accessible_student_ids = [student.id for student in access_service.list_accessible_students(db, user.id)]
        query = query.filter(
            or_(
                Material.student_id.in_(accessible_student_ids),
                and_(
                    Material.student_id.is_(None),
                    or_(
                        Material.uploaded_by == user.id,
                        Material.uploaded_by.in_(accessible_student_ids),
                    ),
                ),
            )
        )
    if source:
        query = query.filter(Material.source == source)
    if mtype:
        query = query.filter(Material.type == mtype)
    if not include_duplicates:
        query = query.filter(Material.duplicate_of_material_id.is_(None))

    items: list[MaterialItem] = []
    for m, uploader in query.order_by(Material.id.desc()).all():
        uploader_name = uploader.display_name or uploader.username if uploader else ""
        items.append(
            MaterialItem(
                id=m.id,
                name=m.name,
                type=m.type,
                source=m.source,
                knowledge_tags=m.knowledge_tags or [],
                recognition_status=m.recognition_status or "pending",
                uploaded_by=uploader_name,
                cos_url=_build_url(m.content_ref or ""),
                created_at=m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
                student_id=m.student_id,
                auto_ready=bool(m.auto_ready),
                is_duplicate=m.duplicate_of_material_id is not None,
            )
        )
    return items
# agg-1
