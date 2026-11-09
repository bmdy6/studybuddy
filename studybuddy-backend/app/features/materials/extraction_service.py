"""素材识别（extraction）服务：幂等识别入口、指纹归一、确认（spec 第六/七章）。

单向依赖 service.can_access_material（§1）：识别前复用访问边界，不重写权限。
"""

import hashlib
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import has_secret, settings
from app.models.material import Material
from app.models.user import User

from .schemas import MaterialExtractionResponse
from .service import MaterialOwnerForbiddenError, build_local_upload_path, can_access_material

logger = logging.getLogger(__name__)

# 文本类素材直接读正文写 recognized_markdown，无需 OCR/视觉。
_TEXT_DIRECT_EXTENSIONS = {".txt", ".md"}
_RECOGNIZABLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
# PDF 素材：pdf-inspector 确定性提取文本型 PDF 的 Markdown（core/pdf_service.py）。
_PDF_EXTENSIONS = {".pdf"}
# PDF 识别 provider 标记。
_PDF_PROVIDER = "pdf_inspector"
# 识别终态：已识别/已确认/自动可用，ensure_extraction(force=False) 直接返回不重识别。
_RECOGNITION_TERMINAL_STATUSES = {"recognized", "confirmed"}
# 内容指纹规范化时去除的 LLM 尾注三行标签（措辞会微变，只对正文算指纹）。
_FOOTER_LABELS = ("识别置信度", "需要人工确认的内容", "适合作为哪类学习素材")


class MaterialRecognitionPreconditionError(ValueError):
    """素材存在，但当前文件状态不满足识别前置条件。"""


def _normalize_markdown_for_fingerprint(markdown: str) -> str:
    """规范化 Markdown 用于内容指纹计算。

    规则（spec 第七章）：
    1. strip 首尾空白，统一换行为 \\n。
    2. 每行 strip，去掉行首尾空白。
    3. 去除 LLM 尾注三行（识别置信度/需要人工确认的内容/适合作为哪类学习素材），
       只对正文算指纹（尾注措辞/百分比会微变）。
    4. 合并连续空行为单个，去尾部空行。
    """
    if not markdown:
        return ""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body_lines: list[str] = []
    for raw in lines:
        line = raw.strip()
        if any(line.startswith(label) for label in _FOOTER_LABELS):
            break  # 命中尾注起始行，其后都是尾注，停止收集正文
        body_lines.append(line)
    # 合并连续空行为单个
    normalized: list[str] = []
    prev_blank = False
    for line in body_lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        normalized.append(line)
        prev_blank = is_blank
    # 去尾部空行
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def _content_fingerprint(markdown: str) -> str | None:
    """识别成功后对规范化 Markdown 算 SHA-256 hex；空正文返回 None。"""
    normalized = _normalize_markdown_for_fingerprint(markdown)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _to_extraction_response(material: Material) -> MaterialExtractionResponse:
    return MaterialExtractionResponse(
        material_id=material.id,
        name=material.name,
        recognition_status=material.recognition_status or "pending",
        raw_text=material.raw_text,
        recognized_markdown=material.recognized_markdown,
        confirmed_markdown=material.confirmed_markdown,
        summary=material.summary,
        content_type=material.content_type,
        recognition_provider=material.recognition_provider,
        recognition_confidence=material.recognition_confidence,
        uncertain_points=material.uncertain_points or [],
        recognized_at=material.recognized_at.isoformat() if material.recognized_at else None,
        confirmed_at=material.confirmed_at.isoformat() if material.confirmed_at else None,
        auto_ready=bool(material.auto_ready),
        content_fingerprint=material.content_fingerprint,
        duplicate_of_material_id=material.duplicate_of_material_id,
    )


def _resolve_recognition_input_path(material: Material) -> str | None:
    """解析素材识别的本地输入路径。

    - local: 素材 -> build_local_upload_path
    - COS 素材（无 local: 前缀且配置了 COS）-> None（由调用方走 download_to_temp）
    返回 None 表示需要走 COS 临时下载。
    """
    if not material.content_ref:
        return None
    if material.content_ref.startswith("local:"):
        return build_local_upload_path(material.content_ref)
    # 无 local: 前缀，COS 存储素材
    if not has_secret(settings.COS_SECRET_ID) or not settings.COS_BUCKET:
        return None
    return None  # COS 素材走临时下载


async def ensure_extraction(
    db: Session, material_id: int, user: User, force: bool = False
) -> MaterialExtractionResponse:
    """幂等识别入口（spec 第六章）。

    - force=False 且已是终态（recognized/confirmed/auto_ready recognized）-> 直接返回，不重识别。
    - force=False 且正在 processing -> 返回当前状态（防并发重复）。
    - force=True -> 强制重识别（保留 confirmed_markdown，不清空）。
    识别完成 -> 写 raw_text/recognized_markdown/... -> 算 content_fingerprint -> 归一 duplicate_of。
    高置信非空 -> auto_ready=True；低置信/有不确定点 -> needs_review；空/失败 -> failed。
    """
    material = db.get(Material, material_id)
    if not material:
        raise ValueError("素材不存在")
    if not can_access_material(db, material, user):
        raise PermissionError("无权访问该素材")

    if not force:
        if material.recognition_status in _RECOGNITION_TERMINAL_STATUSES:
            return _to_extraction_response(material)
        if material.recognition_status == "processing":
            return _to_extraction_response(material)

    if not material.content_ref:
        raise MaterialRecognitionPreconditionError("当前素材文件不可识别")
    ext = os.path.splitext(material.content_ref)[1].lower()
    if (
        ext not in _RECOGNIZABLE_IMAGE_EXTENSIONS
        and ext not in _TEXT_DIRECT_EXTENSIONS
        and ext not in _PDF_EXTENSIONS
    ):
        # doc/xlsx 等暂不解析：状态保持 pending（前端渲染为「已上传·可用」），
        # read_material 会引导用户描述；不抛 failed，避免误导成识别失败。
        raise MaterialRecognitionPreconditionError("当前仅支持图片/txt/md/pdf 素材识别，其他文档解析后续接入")

    # 解析识别输入路径：local: 素材用本地路径；配置了 COS 的无前缀 key 走临时下载；
    # 其余（如 cos: 伪前缀或无法解析）属于不可识别前置条件，抛 422（保留原 /recognize 语义）。
    local_path = _resolve_recognition_input_path(material)
    needs_cos_download = local_path is None
    if needs_cos_download and not (has_secret(settings.COS_SECRET_ID) and settings.COS_BUCKET):
        raise MaterialRecognitionPreconditionError("当前素材文件不可识别")
    if local_path is not None and not os.path.exists(local_path):
        raise MaterialRecognitionPreconditionError("素材文件不存在")

    material.recognition_status = "processing"
    # force 重识别保留 confirmed_markdown（spec 6.1 / 7.2），不清空
    db.commit()

    temp_path: str | None = None
    try:
        if ext in _TEXT_DIRECT_EXTENSIONS:
            # txt/md：直接读正文写 recognized_markdown，无需 OCR/视觉
            if local_path is not None:
                with open(local_path, "rb") as f:
                    raw_bytes = f.read()
            else:
                from app.utils.cos import download_to_temp

                temp_path = await download_to_temp(material.content_ref)
                with open(temp_path, "rb") as f:
                    raw_bytes = f.read()
            text = raw_bytes.decode("utf-8", errors="replace")
            from .markdown_extraction_service import MarkdownExtractionResult

            result = MarkdownExtractionResult(
                markdown=text,
                confidence="high",
                content_type="text",
                provider="text_direct",
                raw_text=text,
            )
        elif ext in _PDF_EXTENSIONS:
            # PDF：pdf-inspector 确定性提取文本型 PDF；扫描/图像型或失败 -> 抛前置条件错误
            # 保留原语义（422 需人工确认），不置 failed、不 500。
            from app.core.pdf_service import extract_pdf_markdown

            if local_path is not None:
                pdf_path = local_path
            else:
                from app.utils.cos import download_to_temp

                temp_path = await download_to_temp(material.content_ref)
                pdf_path = temp_path
            pdf_result = extract_pdf_markdown(pdf_path)
            if pdf_result is None or not (pdf_result.markdown or "").strip():
                raise MaterialRecognitionPreconditionError(
                    "当前 PDF 暂不可识别（扫描/图像型或解析失败），需人工确认"
                )
            from .markdown_extraction_service import MarkdownExtractionResult

            result = MarkdownExtractionResult(
                markdown=pdf_result.markdown,
                confidence="high",
                content_type="",
                provider=_PDF_PROVIDER,
                raw_text=pdf_result.markdown,
            )
        else:
            from .markdown_extraction_service import recognize_images_to_markdown

            if local_path is not None:
                image_paths = [local_path]
            else:
                from app.utils.cos import download_to_temp

                temp_path = await download_to_temp(material.content_ref)
                image_paths = [temp_path]
            result = await recognize_images_to_markdown(image_paths, mode="learning_material")
    except MaterialRecognitionPreconditionError:
        # PDF 扫描/图像型或解析失败：保留原语义（422 需人工确认），回滚 processing 状态，不置 failed。
        material.recognition_status = "pending"
        material.auto_ready = False
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - 识别/下载失败必须回到可重试状态
        logger.warning("素材 %s 识别失败：%s", material_id, exc, exc_info=True)
        material.recognition_status = "failed"
        material.auto_ready = False
        db.commit()
        return _to_extraction_response(material)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    # 写识别结果
    recognized = (result.markdown or "").strip()
    material.raw_text = result.raw_text
    material.recognition_confidence = result.confidence
    material.uncertain_points = result.uncertain_points or []
    material.content_type = result.content_type
    material.recognition_provider = result.provider
    # naive UTC，与 aggregate_daily_facts 的 utc_start/utc_end 窗口口径一致；
    # datetime.now() 写本地墙上时间，非 UTC 机器上晚于 UTC 的识别会落不进当日窗口。
    # microsecond=0：DATETIME 秒级精度对微秒四舍五入会进位越过 utc_end，写秒级杜绝边界 flake。
    material.recognized_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    if not recognized:
        # 空内容（LLM 返回空串/纯空白/识别无文字）-> failed，不进 Agent 上下文
        material.recognized_markdown = None
        material.summary = None
        material.content_fingerprint = None
        material.auto_ready = False
        material.recognition_status = "failed"
        db.commit()
        db.refresh(material)
        return _to_extraction_response(material)

    material.recognized_markdown = result.markdown
    material.summary = result.markdown[:240]
    material.content_fingerprint = _content_fingerprint(result.markdown)

    # 内容指纹归一：查同归属范围 content_fingerprint 命中（排除自身）
    owner = material.student_id
    canonical: Material | None = None
    if material.content_fingerprint:
        q = db.query(Material).filter(
            Material.content_fingerprint == material.content_fingerprint,
            Material.id != material.id,
        )
        if owner is not None:
            q = q.filter(Material.student_id == owner)
        else:
            q = q.filter(Material.student_id.is_(None), Material.uploaded_by == material.uploaded_by)
        canonical = q.order_by(Material.id.asc()).first()

    if canonical is not None:
        # 命中 -> 归一到规范素材，保留本记录与原文件，不删
        material.duplicate_of_material_id = canonical.id
        material.auto_ready = bool(canonical.auto_ready)
        material.recognition_status = "recognized"
    else:
        # 本素材成为规范素材，按置信度计算 auto_ready
        material.duplicate_of_material_id = None
        is_high_conf = result.confidence == "high" and not (result.uncertain_points or [])
        material.auto_ready = is_high_conf
        material.recognition_status = "recognized" if is_high_conf else "needs_review"

    db.commit()
    db.refresh(material)
    return _to_extraction_response(material)


async def recognize_material(db: Session, material_id: int, user: User) -> MaterialExtractionResponse:
    """手动重识别端点的服务入口，语义为强制重识别（保留 confirmed）。

    保留旧 /recognize 端点行为：重识别。现委托 ensure_extraction(force=True)。
    """
    try:
        return await ensure_extraction(db, material_id, user, force=True)
    except MaterialOwnerForbiddenError:
        raise
    except MaterialRecognitionPreconditionError:
        raise
    except PermissionError:
        raise
    except ValueError:
        raise


def get_material_extraction(db: Session, material_id: int, user: User) -> MaterialExtractionResponse:
    material = db.get(Material, material_id)
    if not material:
        raise ValueError("素材不存在")
    if not can_access_material(db, material, user):
        raise PermissionError("无权访问该素材")
    return _to_extraction_response(material)


def confirm_material_extraction(db: Session, material_id: int, markdown: str, user: User) -> MaterialExtractionResponse:
    material = db.get(Material, material_id)
    if not material:
        raise ValueError("素材不存在")
    if not can_access_material(db, material, user):
        raise PermissionError("无权访问该素材")
    confirmed_markdown = markdown.strip()
    if not confirmed_markdown:
        raise MaterialRecognitionPreconditionError("确认稿不能为空")
    material.confirmed_markdown = confirmed_markdown
    material.recognition_status = "confirmed"
    material.confirmed_at = datetime.now()
    db.commit()
    db.refresh(material)
    return _to_extraction_response(material)
