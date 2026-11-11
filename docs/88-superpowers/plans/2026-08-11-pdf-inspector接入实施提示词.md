# 任务：接入 pdf-inspector 作为知了（xcc）的通用 PDF 解析基础设施

## 背景

知了是一个 K12 学习平台（FastAPI 后端，代码在 studybuddy-backend/）。当前 PDF 处理有两个痛点：

1. **素材 PDF 根本不解析**：`app/features/materials/extraction_service.py` 第 141-144 行，遇到 `.pdf` 直接抛 `MaterialRecognitionPreconditionError`（"当前仅支持图片/txt/md 素材识别，PDF/文档解析后续接入"），素材状态永远 pending。
2. **图片/试卷全靠 LLM 视觉模型**：`app/features/materials/markdown_extraction_service.py` 的 `recognize_images_to_markdown` 调 MiMo 视觉模型看图生成 Markdown——慢（几秒）、贵、且 **AI 幻觉导致格式不稳定/内容可能编造**。

解决方案已调研定稿（`~/Documents/40-学习笔记/66-调研/xcc/[P0] PDF解析-PdfInspector调研.md`）：接入 Firecrawl 的开源库 **pdf-inspector**（纯 Rust 确定性解析、MIT、PyPI 有预编译 wheel 0.2.7、无 ML 无外部服务）。它能在 7-11ms 内对**文本型 PDF** 做零幻觉的 Markdown 提取（含中文 CID 字体、表格、多栏），并能在 10-50ms 内分类（text_based/image_based/mixed/scan_with_native_header_text 等）。

分层策略：
```
PDF 输入 → pdf-inspector 分类（免费、确定性）
  → 文本型 → pdf-inspector 直接提取 Markdown（0 幻觉、7ms）
  → 扫描/图像型 → 保留现有视觉模型兜底（本期不做 OCR 路由）
照片（jpg/png）→ 维持现有视觉流程（不动）
```

## 任务范围（本期只做两件事）

1. 新建**通用 PDF 服务** `app/core/pdf_service.py`（core 层，因为以后试卷模块 exams 也要用，不能放 features/materials 里）
2. 素材模块接入：`extraction_service.py` 的 PDF 分支从"抛错不解析"改为"调 pdf_service 提取"

## 架构要求（硬性）

- **符合现有架构**：沿用知了现有的分层与模式。参考 `app/core/ai_service.py`（core 服务）、`app/features/materials/markdown_ocr_service.py`（provider 模式：返回结果 dataclass + provider 字段 + 失败返回 None 由上层兜底）、`app/features/materials/extraction_service.py`（素材识别状态机：processing → recognized/needs_review/failed，写 raw_text/recognized_markdown/content_fingerprint）。
- **通用组件抽离**：pdf_service 必须是通用组件，不依赖 materials 的任何模型/路由。输入是文件路径，输出是纯数据（分类 + markdown + 元信息），任何模块（materials、未来的 exams）都能复用。禁止把 PDF 逻辑写死在 extraction_service 里。
- **不能硬编码**：
  - 扩展名集合、分类结果值、超时、大小限制等常量放模块级常量或 `app/config.py` 的 settings（参考现有 `MARKDOWN_OCR_PROVIDER` 的模式），不散落在函数里
  - PDF 路径解析复用现有的 `_resolve_recognition_input_path` 流程（local 路径 / COS 下载），不要在 pdf_service 里重写一套
- **兜底不破坏现状**：pdf_service 失败（库未装/解析异常/超时）时，素材识别流程要**优雅降级**——保持原来的行为（抛 MaterialRecognitionPreconditionError 或 failed 状态），绝不能 500 或吞异常。扫描/图像型 PDF 不硬做 OCR，返回"需 OCR"语义让上层决定。

## 具体改动点

### 1. 新增 `app/core/pdf_service.py`

```
@dataclass PdfExtractionResult:
    pdf_type: str            # 分类：text_based / image_based / mixed / scan_with_native_header_text / ...
    markdown: str            # 文本型提取结果（空表示无）
    has_encoding_issues: bool
    elapsed_ms: int
    warnings: list[str]

def classify_pdf(path) -> PdfExtractionResult    # 只分类（10-50ms）
def extract_pdf_markdown(path) -> PdfExtractionResult | None  # 分类+提取，文本型返回 markdown；非文本型返回 None
```

- 用 `import pdf_inspector`（延迟导入，参考 markdown_ocr_service.py 对 img2pdf 的处理，未装不影响后端启动）
- 处理 pdf-inspector 的异常（文件不存在、损坏 PDF、解析异常）→ 返回 None 或 warnings，不抛给上层
- 已知小瑕疵：pdf-inspector 标题会过度识别（正文行也可能变 `##`）。**本期不修**（内容准确 > 格式完美），但在 warnings 里标注，留给后续后处理。

### 2. `app/features/materials/extraction_service.py` 接入

- 加模块级常量 `_PDF_EXTENSIONS = {".pdf"}`，`ext` 判断处把 PDF 纳入可识别范围
- 识别分支（约 161 行 `if ext in _TEXT_DIRECT_EXTENSIONS` 附近）：新增 PDF 分支——调 `pdf_service.extract_pdf_markdown`：
  - 成功且有 markdown → 走**现有识别完成流程**（写 raw_text/recognized_markdown/指纹/auto_ready 或 needs_review），provider 记为 "pdf_inspector"
  - 返回 None（扫描/图像型或失败）→ 优雅降级，抛 MaterialRecognitionPreconditionError（保留原语义"该素材需人工确认/暂不可识别"）或按现有状态机置 failed，不能 500
- 复用 `markdown_extraction_service.normalize_markdown_extraction_result` 不需要——pdf-inspector 输出是干净 markdown，直接写库即可（但要去除首尾空白）

### 3. 依赖

- `requirements.txt` 加：`pdf-inspector>=0.2.7,<1`（锁版本上限，参考现有依赖风格）
- 不改 pyproject.toml（该项目依赖以 requirements.txt 为准）

### 4. 测试（必须，TDD）

- 新增 `tests/unit/test_pdf_service.py`：
  - 文本型 PDF → 返回 text_based + 非空 markdown（用项目已有 fixture 或测试内生成最小 PDF）
  - 中文 PDF → 中文提取正确（生成含中文的最小 PDF 或用 fixtures）
  - 损坏/不存在文件 → 返回 None 不抛异常
  - 非文本型（纯图片 PDF）→ 返回 None 或 pdf_type 正确标记
  - 未装库时（mock import 失败）→ 优雅降级不抛
- `tests/unit/test_markdown_extraction_service.py` 或 extraction 相关测试补充：PDF 素材识别分支（mock pdf_service 返回成功/失败两条路径）
- **不写 change-detector 测试**（不断言具体分类值列表、不读源码）

## 验收标准

1. 文本型 PDF 素材上传 → 识别成功，recognized_markdown 有内容、provider=pdf_inspector、状态终态
2. 扫描/图像型 PDF → 不 500，优雅降级（保留原行为语义）
3. `pytest tests/unit/test_pdf_service.py -v` 全过
4. 现有测试不回归：`pytest tests/unit -v` 全过

## 不做（明确排除）

- 试卷模块（exams/batch_service.py）不动——照片流维持现状
- 扫描版 PDF 的 OCR 路由/视觉兜底本期不做（pymupdf 渲染是题库候选，另行立项）
- 前端 WASM 不做
- 标题过度识别的后处理不做（记录 warnings 即可）

## 提交流程（必须）

1. 按模块分批 commit（参考仓库现有提交风格：一次 1-2 个文件）：
   - commit 1：requirements.txt + app/core/pdf_service.py
   - commit 2：extraction_service.py 接入
   - commit 3：tests
2. 推送到远程，开 **GitHub Pull Request**（PR 标题如 `feat(materials): 接入 pdf-inspector 解析文本型 PDF 素材`），PR 描述里写清楚：改了什么、为什么（0 幻觉/7ms/省钱）、验收证据（测试输出）
3. 确保 CI 通过（若有），并在 PR 里贴测试通过截图/输出

## 参考文件

- 调研文档：`~/Documents/40-学习笔记/66-调研/xcc/[P0] PDF解析-PdfInspector调研.md`
- 现有模式：`app/features/materials/markdown_ocr_service.py`（provider 模式）、`app/features/materials/extraction_service.py`（识别状态机）、`app/core/ai_service.py`（core 服务分层）
- pdf-inspector API：`import pdf_inspector; pdf_inspector.process_pdf(path)` 返回含 pdf_type/markdown/has_encoding_issues 的对象（可先 pip install pdf-inspector 在 Python REPL 里看实际字段名，README 在 /tmp/pdf-inspector 或 GitHub firecrawl/pdf-inspector）
