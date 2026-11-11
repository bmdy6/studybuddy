---
title: 学生上传素材 Markdown 化需求设计
date: 2026-07-06
status: proposed
type: requirement-spec
priority: P1
---

# 学生上传素材 Markdown 化需求设计

> **局部替代说明（2026-07-17）**：本文保留原始素材、人工修正、确认稿优先和失败回退设计。自动识别、去重和机器可用状态的当前契约以 `2026-07-17-daily-coach-auto-memory-design.md` 为准：高置信非空结果可以作为 `machine_extracted` 自动供 Agent 使用，但不能升级为 `verified`，也不能覆盖 `confirmed_markdown`。每日摘要可客观展示未完成数量，但不由本素材流程创建独立催办。

## 背景

智学伴下一阶段的重点不是拼外部试卷，而是把学生自己的错题、笔记、每日回顾和上传素材变成长期可用的学习数据。现在素材已经能上传、预览，Agent 也能通过 `read_material` 即时读取图片内容，但这个能力还偏“当场看一眼”：

1. 识别结果没有稳定落库，下一次 Agent 很难可靠引用。
2. 学生无法检查“AI 到底识别对了吗”。
3. 同一张图片/PDF 每次都重新让视觉模型读，慢且浪费。
4. 素材无法和笔记、错题、学习地图形成稳定连接。
5. 拍题链路已经证明“先 Markdown、再确认、再批改”比一次性 JSON 批改更稳，这个中间层应该扩展到普通素材。

这次需求只做“学生上传素材 Markdown 化 MVP”，让素材先成为学生可读、Agent 可读、可确认、可复用的文本资产。

## 核心模型：原始素材 + AI 可读 Markdown 素材

素材不是一个单层概念，应明确拆成两层：

| 层级 | 保存内容 | 主要用户 | 作用 |
|---|---|---|---|
| 原始素材 | 图片、PDF、Word、老师发的资料、学生拍的题等原文件引用 | 学生、家长、系统 | 保真存档、预览、追溯来源，识别质量有争议时能回看原件 |
| Markdown 素材 | 从原始素材转换出的 `recognized_markdown` 和学生确认后的 `confirmed_markdown` | 学生、Agent | 快速阅读、复习、搜索、引用、制定计划和后续学习地图连接 |

原则：

1. 原始素材必须保留，不能因为生成了 Markdown 就丢掉原文件。
2. Markdown 素材不是只给 Agent 看的隐藏数据，学生也要能直接查看，因为它加载快、可复制、可搜索，也更适合复习。
3. Agent 长期读取素材时优先读 `confirmed_markdown`；没有确认稿时可读取带 provider、置信度和不确定点的机器识别稿，并明确标记 `machine_extracted`。
4. 学生在素材页看到的应该是“原件预览 + AI 可读稿”两种视角，而不是只看到下载链接或只看到审核状态。

## 用户价值

### 对学生

- 上传单词表、讲义截图、错题照片、老师发的资料后，不用每次重新解释图片内容。
- 能直接查看 Markdown 素材，加载比原图/PDF 更快，也方便复制、搜索和复习。
- 可以看到 AI 识别稿，发现识别错了能改，不会让错误内容长期影响后续建议。
- 以后问“根据我昨天传的英语资料帮我复习”时，Agent 能直接引用素材。

### 对家长

- 能看到孩子上传了哪些学习资料，以及哪些已经被 AI 整理过。
- 不需要人工逐字整理，只要在重要素材上确认识别稿是否靠谱。
- 后续家长查看学习情况时，可以知道计划和建议依据了哪些真实资料。

### 对 Agent

- 回答前可读取已确认素材 Markdown，不再只依赖当场视觉识别。
- 制定计划、整理笔记、推荐练习时可以引用素材摘要和知识点标签。
- 低置信度素材会先要求用户确认，避免“AI 自嗨总结”污染记忆。

## MVP 范围

第一版只覆盖素材库中已经支持上传的图片和 PDF，不新建第二套素材系统。

### 要做

1. 素材上传后保留原始文件引用，额外生成可追溯的 Markdown 识别稿。
2. 素材列表展示识别状态：未识别、识别中、待确认、已确认、失败。
3. 素材详情/预览里提供“查看识别稿、确认识别稿、重新识别”的入口。
4. 用户可把 AI 识别稿确认为 `confirmed_markdown`；低置信度或不确定点必须引导用户先确认。
5. `read_material` 优先读取 `confirmed_markdown`，没有确认稿时读取 `recognized_markdown` 并提醒未确认；没有识别稿时再走现有即时读图兜底。
6. 学生可在素材页直接阅读 Markdown 素材；已确认稿优先展示，未确认稿要标明“待核对”。
7. Agent 可列出当前学生有权限访问的素材列表，至少包含素材 ID、名称、类型、识别/确认状态和标签，避免学生必须先记住素材编号。
8. Agent 基于素材生成笔记、计划或练习前，要说明依据来自哪份素材。
9. 识别失败时不影响原素材上传和预览，用户仍可手动输入或让 Agent 当场读取。

### 暂不做

1. 不做全国题库、教材库或爬虫入库。
2. 不做复杂富文本编辑器，MVP 先用 Markdown 文本框或确认入口。
3. 不直接引入重型 OCR 模型到主后端 requirements。
4. 不做向量数据库和图数据库；第一版仍用 MySQL 字段和现有检索。
5. 不自动把所有素材生成笔记或错题，长期记忆必须有用户确认。

## 复用优先原则

这块不能重复造轮子。实现前必须按下面顺序复用：

1. **项目内复用**
   - 复用 `materials` 表、素材上传/列表/预览/权限逻辑。
   - 复用 `read_material` Agent 工具入口，不新增第二个“读素材”工具。
   - 复用已做的拍题 Markdown 提示词、图片压缩、MiMo 视觉读取、`photo_grading_service` 的 Markdown 归一化思路和可选 `markdown_ocr_service` provider。
   - 复用现有 AntD、Markdown 渲染、页面壳、颜色 token，不新建一套素材 UI 框架。
   - 当前拍题导入已经有 `recognize_homework_photo_markdown`、`markdown_ocr_service.recognize_photos_to_markdown`、`normalize_photo_markdown_result`、`_encode_photo_for_vision` 和 `_extract_llm_message_text`；实现素材 Markdown 化前必须先把这些通用能力抽离，不能复制到素材模块。

2. **开源轮子候选**
   - `MinerU`：偏 PDF/文档解析，适合后续离线服务评测，主服务不直接依赖。
   - `marker`：PDF 转 Markdown 能力成熟，但模型体积和冷启动需要单独评估。
   - `Docling`：文档结构化解析适合 PDF/Office 后续扩展。
   - `Pix2Text`：公式和中文 OCR 可继续评测，但之前真实整页照片效果不稳定，不能默认上线。

3. **接入方式**
   - MVP 默认继续用 MiMo 视觉生成 Markdown，保证现在链路能跑。
   - 外部 OCR/文档解析只通过 provider 或 CLI 适配层接入，例如 `MARKDOWN_OCR_PROVIDER=external_cli`，失败或超时回退 MiMo。
   - 如果某个开源工具质量达标，先作为独立脚本或服务跑评测，不把 GB 级模型下载、冷启动、GPU/CPU 依赖绑进学生实时请求。

参考项目：

- MinerU: https://github.com/opendatalab/MinerU
- marker: https://github.com/VikParuchuri/marker
- Docling: https://github.com/docling-project/docling
- Pix2Text: https://github.com/breezedeus/Pix2Text

## 数据设计

优先在现有素材模型上扩展字段，避免新建平行表。若 MySQL 5.7 迁移成本或字段过多，可拆 `material_extractions` 表，但 service 对外保持同一个素材接口。

建议字段：

| 字段 | 说明 |
|---|---|
| `raw_text` | OCR/视觉模型原始文本，便于排查 |
| `recognized_markdown` | AI 生成的 Markdown 识别稿 |
| `confirmed_markdown` | 用户确认或编辑后的最终稿 |
| `summary` | 简短摘要，供列表和 Agent 上下文快速读取 |
| `content_type` | `homework_photo`、`wrong_question_photo`、`word_list`、`lecture_note`、`textbook_page`、`other` |
| `recognition_status` | `pending`、`processing`、`recognized`、`needs_review`、`confirmed`、`failed` |
| `recognition_provider` | `mimo`、`external_cli`、`manual` 等 |
| `recognition_confidence` | `high`、`medium`、`low` |
| `uncertain_points` | JSON 数组，记录需要人工确认的地方 |
| `recognized_at` | 最近识别时间 |
| `confirmed_at` | 用户确认时间 |

权限仍沿用素材权限：学生只看自己的素材，家长只能看自己绑定学生和自己上传的素材。所有识别稿、确认稿和摘要都必须跟原素材同权限。

## 产品流程

### 上传后

1. 用户上传素材。
2. 系统立即保存原文件，列表出现新素材。
3. 后端触发识别任务或前端提供“开始识别”按钮；MVP 可先同步识别，但要有超时和失败兜底。
4. 识别完成后状态变成“待确认”或“已识别”。

### 确认识别稿

1. 用户打开素材详情。
2. 左侧或上方看原文件预览，右侧或下方看 Markdown 识别稿。
3. 用户可以确认，也可以要求重新识别。
4. 如果识别稿有 `[?]`、低置信度、学生作答不清晰，按钮文案要提醒“先确认再让 AI 使用”。

### Agent 使用素材

1. 用户在聊天里说“根据我上传的单词表帮我复习”。
2. Agent 先查素材。
3. 有确认稿：直接读取 `confirmed_markdown`。
4. 只有识别稿：读取 `recognized_markdown`，但回答中提示“这份素材还没确认”。
5. 没有识别稿：调用现有即时读图能力，并建议用户把结果保存为识别稿。
6. Agent 输出笔记、计划、练习前，明确引用素材名称和知识点。

### Agent 列出素材

1. 用户问“我有哪些素材”“看看我上传过什么资料”。
2. Agent 不应回答“没有查看素材列表的功能”。
3. Agent 应调用素材列表能力，返回最近素材清单：素材 ID、名称、类型、确认状态、标签和上传时间。
4. 已确认 Markdown 素材要提示“可直接用于复习/整理笔记”；未确认素材要提示“建议先查看识别稿并确认”。

## 后端边界

### API 建议

- `POST /api/material/{id}/recognize`：触发识别或重新识别。
- `GET /api/material/{id}/extraction`：读取识别稿、确认稿、状态、摘要和不确定点。
- `PUT /api/material/{id}/extraction/confirm`：保存用户确认稿。
- `GET /api/material`：现有素材列表接口应作为 Agent 列表工具的数据来源之一，后端仍必须做权限校验。

### Service 边界

- `material_service` 只负责素材权限、文件引用、列表和删除。
- 新增或扩展 `material_extraction_service` 负责识别状态、provider 调用、确认稿保存和摘要提取。
- 新增通用 `markdown_extraction_service`，承接“图片/PDF 路径列表 → Markdown 识别结果”的纯识别能力；拍题导入和素材识别都调用它。
- `photo_grading_service` 只保留拍题批改、错题保存、学生作答核对等拍题领域逻辑；通用 Markdown 清洗、置信度、不确定点、内容类型提取应迁到通用服务，拍题通过兼容 wrapper 调用。
- `agent_loop` 只通过 service 读素材内容，不直接拼 SQL 或访问文件系统。
- OCR provider 必须有超时、错误记录和可观测耗时。

## 前端体验

第一版优先改素材管理页，不单独做复杂工作台：

1. 素材列表新增识别状态标签和“识别/查看识别稿”操作。
2. 预览弹窗增加 Markdown 识别稿区域，保持简洁，不做大而复杂的编辑器；学生可把 Markdown 作为快速阅读视图使用。
3. 确认前按钮文案要让用户知道会影响后续 Agent 记忆，例如“确认，之后让 AI 按这份内容使用”。
4. 失败时显示可恢复路径：重新识别、手动补充、回到聊天让 Agent 当场看图。
5. 移动端先保证能看和确认，不追求双栏编辑。

## 失败兜底

| 场景 | 处理 |
|---|---|
| OCR/视觉超时 | 状态标记 `failed` 或 `needs_review`，保留原素材，可重新识别 |
| 识别质量低 | 不自动确认，列出不确定点，让用户确认 |
| 用户不想确认 | Agent 可临时读取，但回答必须提示“未确认” |
| 原素材预览失败 | 不影响查看已有 Markdown；提示检查文件链接 |
| 外部 OCR provider 异常 | 回退 MiMo 或手动流程，不阻塞上传 |
| 重复识别 | 覆盖 `recognized_markdown` 前保留确认稿；已确认稿不被自动覆盖 |

## 验收标准

### 自动化

1. 素材上传后能保存并返回识别状态字段。
2. 无权限用户不能读取或确认别人的素材识别稿。
3. `read_material` 优先返回 `confirmed_markdown`，其次返回 `recognized_markdown`，最后才回退现有即时读取。
4. Agent 素材列表能力只能返回当前用户有权限访问的素材，并包含确认状态。
5. provider 超时或失败时不会影响素材上传，也不会让接口 500。

### 真实浏览器

1. 用学生账号上传一张真实学习图片，素材列表能看到状态。
2. 打开素材预览能看到原图和 Markdown 识别稿。
3. 确认识别稿后，聊天里询问这份素材，Agent 能基于确认稿回答。
4. 学生直接查看 Markdown 素材时，页面加载快、文本可读，不需要每次打开原图。
5. 用户问“我有哪些素材”时，Agent 能列出素材清单，而不是要求用户先提供素材编号。
6. 家长账号只能看到自己或绑定学生的素材，不能越权。
7. 页面文案不让学生误以为“AI 已经百分百识别正确”。

## 外部文章启发：PDF/文档解析应走 Markdown/JSON 中间层

参考文章：`https://www.bestblogs.dev/article/RAW_ff0178bd`。文章讨论 2026 年开源结构化 PDF/文档抽取模型，并把能力大致分为两类：一类按固定 schema 抽取字段，适合发票、报告等结构化任务；另一类把复杂文档转换为 Markdown/JSON 等中间表示，适合让人和 AI 继续阅读、检索和复用。

对智学伴的启发：

1. 学习资料不是发票，第一目标不是抽几个字段，而是保留题干、讲义结构、公式、表格、学生作答痕迹和不确定点，所以 Markdown 中间层更适合 MVP。
2. PDF/Word 后续可以评测 MinerU、marker、Docling 等文档解析工具，但它们应接入为 provider，不应把重依赖直接绑进主后端。
3. 解析结果必须给学生看和确认，不能直接进入长期记忆，否则错误 OCR 会污染后续计划、笔记和学习地图。
4. 长期方向可以在 Markdown 之上再生成结构化 JSON、知识点标签和学习地图节点，但原始素材和确认稿仍是可追溯底座。

### Live/真实样本

1. 至少用 1 张真实微信图片跑通上传、识别、确认、Agent 引用全链路。
2. 记录耗时：图片压缩、OCR/provider、Agent 引用各自耗时。
3. 如果使用外部 OCR provider，要和 MiMo 输出做最小对比，不达标不默认启用。

## 分阶段实施建议

### 第零步：先抽通用 Markdown 识别层

先从拍题导入里抽出通用能力，再做素材库，不允许在素材模块复制一份。

建议抽出：

1. `MarkdownExtractionResult`：包含 `markdown`、`confidence`、`uncertain_points`、`content_type`、`raw_text`、`provider`、`elapsed_ms`、`warnings`。
2. `normalize_markdown_extraction_result(raw_text)`：替代现在拍题专用的 `normalize_photo_markdown_result`，兼容识别置信度、需要人工确认、适合作为哪类学习素材等字段。
3. `recognize_images_to_markdown(image_paths, mode)`：统一外部 OCR provider、MiMo 回退、图片压缩和耗时记录；`mode` 可先支持 `homework_photo` 和 `learning_material`，不同模式只换 prompt。
4. 兼容层：保留 `recognize_homework_photo_markdown` 对外工具名和测试，但内部改为调用通用服务，避免破坏现有拍题链路。

### 第一步：需求确认后做 MVP

只做现有素材库字段/API/页面/Agent 读取优先级，不做复杂异步队列。若同步识别超过可接受时长，先做“用户点击识别并等待”的明确状态。

### 第二步：异步与批量

当素材多起来后，再做后台任务、批量识别、识别队列和重试。

### 第三步：学习地图

确认稿和知识点标签稳定后，再把素材连接到错题、笔记和学习地图节点。

## 待用户确认的问题

当前建议的 MVP 取舍是：先让素材库能“识别、确认、被 Agent 稳定读取”，不追求一次性做完 OCR 工具链和学习地图。你确认后，下一步再写实施计划并开始做。
