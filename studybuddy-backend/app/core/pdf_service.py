"""通用 PDF 解析服务（core 层，materials / 试卷 exams 通用）。

包装 pdf-inspector（Firecrawl 开源，纯 Rust 确定性解析，无 ML 无外部服务）：
- 文本型 PDF：7-11ms 零幻觉提取 Markdown（含中文 CID 字体、表格、多栏）
- 扫描/图像型 PDF：不硬做 OCR，返回"非文本型"语义由上层决定

设计约束：
- 输入是文件路径，输出是纯数据（分类 + markdown + 元信息），不依赖任何 features 模块
- pdf-inspector 延迟导入：未安装时后端仍可启动，调用返回 None 由上层兜底
- 异常（文件不存在/损坏/解析失败）内部消化返回 None 或 warnings，不抛给上层
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 分类结果值（pdf-inspector 确定性分类，不含 ML）
_TEXT_BASED_TYPE = "text_based"
_NON_TEXT_TYPES = {"scanned", "image_based", "mixed", "scan_with_native_header_text"}

# pdf-inspector 标题过度识别（正文行也可能变 ##）为已知小瑕疵，
# 本期不修（内容准确 > 格式完美），提取时在 warnings 里标注，留给后续后处理。
_TITLE_HEURISTIC_WARNING = "pdf-inspector 标题过度识别为已知小瑕疵（正文行可能变 ##），内容准确但格式可能不完美"


@dataclass
class PdfExtractionResult:
    """PDF 解析结果：分类 + Markdown + 元信息。"""

    pdf_type: str  # text_based / scanned / image_based / mixed / ...
    markdown: str  # 文本型提取结果（空表示无）
    has_encoding_issues: bool
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)


def _import_pdf_inspector():
    """延迟导入 pdf-inspector；未安装返回 None（上层优雅降级）。"""
    try:
        import pdf_inspector  # type: ignore[import-not-found]

        return pdf_inspector
    except ImportError:
        logger.warning("pdf-inspector 未安装，PDF 解析降级为不可用")
        return None


def _to_result(pdf_type: str, markdown: str, elapsed_ms: int, has_encoding_issues: bool) -> PdfExtractionResult:
    warnings: list[str] = []
    if has_encoding_issues:
        warnings.append("PDF 存在编码问题（坏字体），提取内容可能不完整")
    if pdf_type == _TEXT_BASED_TYPE:
        warnings.append(_TITLE_HEURISTIC_WARNING)
    return PdfExtractionResult(
        pdf_type=pdf_type,
        markdown=markdown,
        has_encoding_issues=has_encoding_issues,
        elapsed_ms=elapsed_ms,
        warnings=warnings,
    )


def classify_pdf(path: str) -> PdfExtractionResult | None:
    """只分类 PDF（10-50ms）。失败返回 None 不抛异常。"""
    pdf_inspector = _import_pdf_inspector()
    if pdf_inspector is None:
        return None
    started = time.perf_counter()
    try:
        raw = pdf_inspector.classify_pdf(path)
    except Exception as exc:  # noqa: BLE001 - 库内部异常（文件不存在/损坏/解析失败）统一降级
        logger.warning("PDF 分类失败 %s：%s", path, exc)
        return None
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    pdf_type = getattr(raw, "pdf_type", "") or ""
    return _to_result(pdf_type, "", elapsed_ms, False)


def extract_pdf_markdown(path: str) -> PdfExtractionResult | None:
    """分类 + 提取。

    文本型 PDF 返回含 markdown 的结果；非文本型（扫描/图像）或失败返回 None，
    由上层决定是否走 OCR/视觉兜底。不抛异常。
    """
    pdf_inspector = _import_pdf_inspector()
    if pdf_inspector is None:
        return None
    started = time.perf_counter()
    try:
        raw = pdf_inspector.process_pdf(path)
    except Exception as exc:  # noqa: BLE001 - 库内部异常统一降级
        logger.warning("PDF 提取失败 %s：%s", path, exc)
        return None
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    pdf_type = getattr(raw, "pdf_type", "") or ""
    if pdf_type not in _NON_TEXT_TYPES:
        # 文本型（text_based 等）：返回提取的 markdown
        markdown = getattr(raw, "markdown", "") or ""
        has_encoding_issues = bool(getattr(raw, "has_encoding_issues", False))
        return _to_result(pdf_type, markdown, elapsed_ms, has_encoding_issues)

    # 非文本型（扫描/图像）：返回 None，由上层决定是否走 OCR/视觉兜底
    logger.info("PDF 为非文本型 %s（%s），返回 None 交由上层处理", pdf_type, path)
    return None
