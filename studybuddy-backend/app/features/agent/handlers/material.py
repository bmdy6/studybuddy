"""Agent 素材工具处理器（read_material / list_materials）+ 素材元数据建议。

拆自 app/core/agent_loop.py。_handle_read_material 复用通用 markdown_extraction_service
做视觉识别，_handle_list_materials 汇总学生素材清单。
依赖方向：单向依赖 context（_material_status_label/_material_ai_readiness）+ core.ai_service
（更稳定 #2）+ features.materials（同层业务）。_suggest_material_metadata/_dedupe_keep_order
是 material 专用辅助，随 handler 内聚于此。
"""
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core import ai_service
from app.prompts import load
from app.features.materials.markdown_extraction_service import extract_llm_message_text
from app.utils.image import encode_image_for_vision
from ..context import _material_ai_readiness, _material_status_label

logger = logging.getLogger(__name__)

# 大内容（教材等）直接返回会撑爆 LLM 上下文：超过该字符数时按章节切片或返回目录。
_SECTION_THRESHOLD_CHARS = 30000
# 超阈值未切片时返回的目录预览长度。
_TOC_PREVIEW_CHARS = 3000
# 章节标题匹配：任意标题级别 + Unit N（pdf-inspector 对单元标题的级别识别不稳定，
# 同一本教材 Unit 1 可能是 ####、Unit 3 可能是 #####，因此不锁级别，只看文本）。
_UNIT_HEADING_PATTERN = re.compile(r"^#{1,6}\s*Unit\s+(\d+)\s*$", re.IGNORECASE)


def _build_section_index(markdown: str) -> list[dict[str, Any]]:
    """构建章节索引：匹配 Unit N 标题（任意级别），每个单元取首次出现。"""
    lines = markdown.split("\n")
    index: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, line in enumerate(lines):
        m = _UNIT_HEADING_PATTERN.match(line.strip())
        if m:
            num = int(m.group(1))
            if num not in seen:
                seen.add(num)
                index.append({"num": num, "line_no": i, "title": line.strip()})
    return index


def _slice_markdown_by_section(markdown: str, section: str) -> dict[str, Any] | None:
    """按 section（'Unit 3' 或 '3'）返回对应章节区间；找不到或无索引返回 None。"""
    index = _build_section_index(markdown)
    if not index:
        return None
    m = re.match(r"^\s*(?:unit\s*)?(\d+)\s*$", section.strip(), re.IGNORECASE)
    if not m:
        return None
    target = int(m.group(1))
    pos = next((i for i, item in enumerate(index) if item["num"] == target), None)
    if pos is None:
        return None
    lines = markdown.split("\n")
    start = index[pos]["line_no"]
    end = index[pos + 1]["line_no"] if pos + 1 < len(index) else len(lines)
    return {
        "title": index[pos]["title"],
        "content": "\n".join(lines[start:end]),
        "total_chars": len(markdown),
    }


def _build_section_toc(markdown: str) -> list[str]:
    """生成章节目录（标题行列表），供 Agent 选择 section。"""
    return [item["title"] for item in _build_section_index(markdown)]


def _apply_section(content: str, section: str | None) -> dict[str, Any]:
    """对大内容应用 section 切片；返回 content/sectioned/section_title/toc/hint。

    - 传 section：命中返回对应区间；未命中返回 None + 提示 + 目录。
    - 未传 section 且超阈值：返回截断预览 + 目录 + 提示。
    - 小内容：原样返回。
    """
    if section:
        sliced = _slice_markdown_by_section(content, section)
        if sliced:
            section_content = sliced["content"]
            # 切片结果也可能过大（如最后一个单元含附录），超阈值截断保护
            if len(section_content) > _SECTION_THRESHOLD_CHARS:
                return {
                    "content": section_content[:_TOC_PREVIEW_CHARS],
                    "sectioned": False,
                    "section_title": sliced["title"],
                    "toc": _build_section_toc(content),
                    "hint": f"章节「{sliced['title']}”仍较大已截断，可再细分范围或换章节。",
                }
            return {
                "content": section_content,
                "sectioned": True,
                "section_title": sliced["title"],
                "toc": _build_section_toc(content),
                "hint": None,
            }
        return {
            "content": None,
            "sectioned": False,
            "section_title": None,
            "toc": _build_section_toc(content),
            "hint": f"找不到章节「{section}”，可用章节见 toc。",
        }
    if len(content) > _SECTION_THRESHOLD_CHARS:
        return {
            "content": content[:_TOC_PREVIEW_CHARS],
            "sectioned": False,
            "section_title": None,
            "toc": _build_section_toc(content),
            "hint": "内容较长已截断，可用 section 参数按章节读取（如 section=\"Unit 3\"）。",
        }
    return {"content": content, "sectioned": False, "section_title": None, "toc": [], "hint": None}


def _dedupe_keep_order(items: list[str], limit: int = 8) -> list[str]:
    """按出现顺序去重并截断。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _suggest_material_metadata(content: str) -> dict[str, Any]:
    """根据视觉识别文本给素材生成摘要、标签和内容类型建议。"""
    text = " ".join((content or "").split())
    lower = text.lower()
    tags: list[str] = []
    content_type = "学习资料"

    keyword_rules = [
        ("英语", ["英语", "english", "word", "sentence", "grammar"]),
        ("词汇", ["单词", "词汇", "vocabulary", "word list"]),
        ("语法", ["语法", "时态", "从句", "grammar", "tense"]),
        ("课文", ["课文", "阅读", "passage", "text"]),
        ("数学", ["数学", "函数", "方程", "几何", "计算"]),
        ("语文", ["语文", "古诗", "作文", "阅读理解"]),
    ]
    for tag, keywords in keyword_rules:
        if any(keyword in lower or keyword in text for keyword in keywords):
            tags.append(tag)

    if any(word in text for word in ["单词", "词汇"]) or "vocabulary" in lower or "word list" in lower:
        content_type = "单词表"
    elif any(word in text for word in ["语法", "时态", "从句"]) or "grammar" in lower:
        content_type = "语法点"
    elif any(word in text for word in ["课文", "阅读"]) or "passage" in lower:
        content_type = "课文/阅读"
    elif any(word in text for word in ["笔记", "板书", "要点"]):
        content_type = "笔记"

    summary = text[:120] if text else ""
    if len(text) > 120:
        summary += "…"
    return {
        "suggested_summary": summary,
        "suggested_tags": _dedupe_keep_order(tags),
        "suggested_content_type": content_type,
    }



async def _handle_read_material(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """用视觉读素材图片内容。复用 exam_batch 的视觉调用模式。

    非图片素材返回文件名+类型，引导用户描述。图片识别失败返回 fallback_hint。
    """
    import os

    from app.models.material import Material
    from app.models.user import User
    from app.features.materials.extraction_service import (
        MaterialRecognitionPreconditionError,
        ensure_extraction,
    )
    from app.features.materials.service import (
        build_local_upload_path,
        can_access_material,
    )

    material_id = args.get("material_id")
    section = args.get("section") or None
    if not material_id:
        return {"error": "缺少 material_id"}
    m = db.get(Material, int(material_id))
    if not m:
        return {"error": f"素材 {material_id} 不存在"}
    user = db.get(User, teacher_id)
    if not user:
        return {"error": "当前用户不存在", "material_id": material_id}
    if not can_access_material(db, m, user):
        raise PermissionError("无权读取该素材")

    # 内容指纹归一：duplicate 素材读取时归一到规范素材（spec 8.2）
    if getattr(m, "duplicate_of_material_id", None):
        canonical = db.get(Material, m.duplicate_of_material_id)
        if canonical and can_access_material(db, canonical, user):
            m = canonical

    # 懒识别：无缓存内容时触发 ensure_extraction（图片走视觉、txt/md 直读正文），
    # 结果写 recognized_markdown 并缓存，后续读取直接走缓存，不重复调视觉 LLM。
    # needs_review/recognized 已有 recognized_markdown 不会进这里，避免重复识别。
    if not m.confirmed_markdown and not m.recognized_markdown:
        if m.recognition_status == "processing":
            # 并发识别中：不重复触发，提示稍后重读
            return {
                "material_id": m.id,
                "name": m.name,
                "type": m.type,
                "content": None,
                "recognition_status": "processing",
                "fallback_hint": "这份素材正在识别中，请稍等片刻再读取。",
            }
        try:
            await ensure_extraction(db, m.id, user, force=False)
            db.refresh(m)
        except MaterialRecognitionPreconditionError:
            # PDF/doc 等暂不支持自动识别，走下面非图片兜底引导用户描述
            pass
        except Exception:  # noqa: BLE001 - 识别异常走下面图片实时视觉/非图片兜底
            logger.warning("read_material 懒识别失败：material_id=%s", material_id, exc_info=True)

    if m.confirmed_markdown:
        suggestions = _suggest_material_metadata(m.confirmed_markdown)
        sliced = _apply_section(m.confirmed_markdown, section)
        return {
            "material_id": m.id,
            "name": m.name,
            "type": m.type,
            "content": sliced["content"],
            "content_source": "confirmed_markdown",
            "needs_confirmation": False,
            "recognition_status": m.recognition_status,
            "recognition_confidence": m.recognition_confidence,
            "uncertain_points": m.uncertain_points or [],
            "sectioned": sliced["sectioned"],
            "section_title": sliced["section_title"],
            "toc": sliced["toc"],
            **suggestions,
            "summary": f"已读取已确认素材「{m.name}”的 Markdown 内容：{m.confirmed_markdown[:100]}",
        }

    if m.recognized_markdown:
        suggestions = _suggest_material_metadata(m.recognized_markdown)
        # auto_ready=True 的高置信非空结果 Agent 可直接读，无需确认（spec 8.3）
        auto_ready = bool(getattr(m, "auto_ready", False))
        sliced = _apply_section(m.recognized_markdown, section)
        result_block = {
            "material_id": m.id,
            "name": m.name,
            "type": m.type,
            "content": sliced["content"],
            "content_source": "auto_ready_markdown" if auto_ready else "recognized_markdown",
            "needs_confirmation": not auto_ready,
            "recognition_status": m.recognition_status,
            "recognition_confidence": m.recognition_confidence,
            "uncertain_points": m.uncertain_points or [],
            "sectioned": sliced["sectioned"],
            "section_title": sliced["section_title"],
            "toc": sliced["toc"],
            **suggestions,
            "summary": f"已读取素材「{m.name}”的 Markdown 内容：{m.recognized_markdown[:100]}",
        }
        if sliced["hint"] or not auto_ready:
            hints: list[str] = []
            if sliced["hint"]:
                hints.append(sliced["hint"])
            if not auto_ready:
                hints.append("这份素材还没有人工确认，使用前请提醒用户核对识别是否准确。")
            result_block["fallback_hint"] = "；".join(hints)
        return result_block

    # 非图片：返回文件名+类型，引导用户描述（pdf/doc 等暂不解析内容）
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    ext = os.path.splitext(m.content_ref or "")[1].lower()
    if ext not in image_exts:
        return {
            "material_id": material_id,
            "name": m.name,
            "type": m.type,
            "content": None,
            "fallback_hint": f"这是 {m.type} 素材「{m.name}」，非图片无法直接识别内容，请用户简单描述里面是什么。",
        }

    # 图片：本地文件读 base64 喂 MiMo 视觉（复用 exam_batch 的调用方式）
    if not m.content_ref or not m.content_ref.startswith("local:"):
        return {"error": "素材文件不可访问（非本地存储）", "material_id": material_id}
    local_path = build_local_upload_path(m.content_ref)
    if not os.path.exists(local_path):
        return {"error": "素材文件不存在", "material_id": material_id}

    try:
        resp = await ai_service.call_llm(
            messages=[
                {
                    "role": "user",
                    "content": [
                        encode_image_for_vision(local_path),
                        {
                            "type": "text",
                            "text": load("material_vision/material_recognition"),
                        },
                    ],
                }
            ],
            max_tokens=3000,  # MiMo 视觉识别会先在 reasoning_content 思考，需足够额度
        )
        msg = resp.choices[0].message
        # MiMo 可能把识别结果放 reasoning_content（content 为空），复用通用提取
        content_desc = extract_llm_message_text(msg)
        suggestions = _suggest_material_metadata(content_desc)
        return {
            "material_id": material_id,
            "name": m.name,
            "type": m.type,
            "content": content_desc,
            **suggestions,
            "summary": f"已读取素材「{m.name}」的内容：{content_desc[:100]}",
        }
    except Exception as e:  # noqa: BLE001  视觉失败回退
        logger.warning("读取素材视觉识别失败：material_id=%s", material_id, exc_info=True)
        return {
            "error": f"视觉识别失败：{e}",
            "material_id": material_id,
            "name": m.name,
            "fallback_hint": "图片识别没成功，请用户简单描述素材内容。",
        }


async def _handle_list_materials(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """列出当前账号有权限访问的素材，供 Agent 回答“我有哪些素材”。

    权限不在这里重写，统一复用 material_service.list_materials。
    """
    from app.models.user import User
    from app.features.materials import service as material_service

    user = db.get(User, teacher_id)
    if not user:
        return {"error": "当前用户不存在"}

    raw_limit = args.get("limit", 10)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 20))

    all_items = material_service.list_materials(
        db,
        user,
        source=args.get("source") or None,
        mtype=args.get("type") or args.get("mtype") or None,
        mode=getattr(user, "mode", "study") if user.role == "student" else None,
    )
    returned = all_items[:limit]
    materials = []
    for item in returned:
        status = getattr(item, "recognition_status", None)
        materials.append(
            {
                "id": getattr(item, "id", None),
                "name": getattr(item, "name", ""),
                "type": getattr(item, "type", ""),
                "source": getattr(item, "source", ""),
                "knowledge_tags": getattr(item, "knowledge_tags", []) or [],
                "recognition_status": status or "pending",
                "status_label": _material_status_label(status),
                "ai_readiness": _material_ai_readiness(status),
                "uploaded_by": getattr(item, "uploaded_by", ""),
                "created_at": getattr(item, "created_at", ""),
            }
        )

    if not all_items:
        return {
            "materials": [],
            "count": 0,
            "total": 0,
            "summary": "当前没有可访问的素材。可以引导学生上传错题、讲义、单词表或课堂笔记图片。",
        }

    return {
        "materials": materials,
        "count": len(materials),
        "total": len(all_items),
        "summary": (
            f"共找到 {len(all_items)} 个素材，返回最近 {len(materials)} 个。"
            "已确认 Markdown 可直接用于复习/讲解；未确认素材建议先确认识别稿。"
        ),
    }
