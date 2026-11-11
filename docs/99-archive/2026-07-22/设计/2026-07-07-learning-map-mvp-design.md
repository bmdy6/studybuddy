---
title: 错题掌握与学习地图 MVP 设计
date: 2026-07-07
status: proposed
type: requirement-spec
priority: P1
---

# 错题掌握与学习地图 MVP 设计

## 背景

智学伴当前已经具备几块关键资产：

- 错题本：`error_book.knowledge_tags`、错题次数、最近错题时间。
- 复盘笔记：`notes.knowledge_tags`、`category=错题复盘`、`source_ref=[error_book.id]`。
- 素材确认稿：`materials.confirmed_markdown`、素材标签和确认状态。
- 学习计划反馈：`study_plan_items.related_tags`、任务完成/跳过状态。
- Agent 学习记忆：已经会读取近期高频错题、代表性错题、错题复盘笔记和最近素材摘要。

但这些能力现在分散在错题本、笔记、素材、学习计划和对话里。学生还缺一个页面能直观看到：

- 我最近反复错什么。
- 哪些知识点已经有复盘笔记或素材。
- 哪些点还需要继续练。
- 点进去后下一步该做什么。

学习地图第一版要把这些真实数据串起来，而不是做一个漂亮但空泛的知识图谱。

## 目标

1. 用现有 MySQL 数据聚合学习地图节点，不引入图数据库。
2. 每个知识点节点展示红/黄/绿掌握状态。
3. 点击知识点能看到相关错题、复盘笔记、已确认素材和计划反馈。
4. Agent 回答“我最近最该补什么”时读取同一套掌握状态摘要，避免页面和对话口径不一致。
5. 页面要让学生觉得“很厉害”，但交互保持简洁、可行动，不做压过学习内容的炫技动画。

## 非目标

- 不做全国课程标准知识点体系。
- 不做复杂图数据库、Neo4j 或图推理。
- 不做自动把未确认素材、未确认错题识别稿写入长期掌握状态。
- 不做 AI 自动判定“已经掌握”并落库。掌握状态第一版由现有数据规则计算，可重算。
- 不做大型可拖拽画布或三维图谱。
- 不把学习地图作为唯一真相；点进去仍能回到错题、笔记、素材和计划原始记录。

## 三种方案

### 方案 A：增强现有学情诊断页

做法：在 `/diagnosis` 增加盲区、笔记数和素材数。

优点：

- 改动最小。
- 复用现有诊断接口和页面。

问题：

- 更像统计报表，不像学习地图。
- 不容易表达错题、笔记、素材、计划之间的关系。
- 学生点击后的行动路径弱。

### 方案 B：新增学习地图聚合接口和页面

做法：新增 `learning_map_service` 聚合现有数据，新增 `/learning-map` 页面展示知识点节点和详情下钻。

优点：

- 页面和 Agent 可以共用同一套聚合逻辑。
- 能同时展示红黄绿状态、关联资料和下一步建议。
- 不引入新存储，不重复造轮子。
- 适合当前家庭内测，后续可以自然升级成更强的学习图谱。

问题：

- 需要新增一条 API、一个页面和一组类型。
- 掌握状态规则要写清楚，否则用户会误解。

### 方案 C：直接做知识图谱/图数据库

做法：引入图数据库或图结构表，把错题、笔记、素材、计划都建成节点和边。

优点：

- 长期扩展空间大。
- 可做复杂关系查询。

问题：

- 当前数据量和关系复杂度还不需要。
- 部署、迁移、同步和权限复杂度都会上升。
- 容易变成架构优先，而不是学生马上能用。

## 推荐方案

采用 **方案 B：新增学习地图聚合接口和页面**。

第一版只做一个可重算的聚合视图，不新增掌握状态表。后端每次从现有业务表读数据，生成学习地图响应。这样不会污染长期事实，也不需要处理状态迁移。

## 数据口径

### 知识点节点来源

知识点来自以下字段，统一做去空、去重、短文本清洗：

| 来源 | 字段 | 用途 |
|---|---|---|
| 错题 | `ErrorBook.knowledge_tags` | 节点主来源，计算错误次数和最近错误 |
| 笔记 | `Note.knowledge_tags` | 判断是否已有复盘或学习记录 |
| 素材 | `Material.knowledge_tags`，仅 `confirmed_markdown` 或 `recognition_status=confirmed` | 判断是否有可复习素材 |
| 计划 | `StudyPlanItem.related_tags` | 判断是否安排过练习、完成或跳过 |

没有知识点标签的数据不进入地图节点，但可以在页面空态中提醒“先给错题/笔记补标签”。

### 掌握状态规则

第一版使用可解释规则，不用 AI 黑盒判断。

| 状态 | 规则 | 页面文案 |
|---|---|---|
| 红色 `weak` | 错题累计次数 >= 3，或最近 14 天仍有错题且没有复盘笔记 | 需要优先补 |
| 黄色 `reviewing` | 有错题，但已有复盘笔记、已确认素材或最近计划任务 | 正在巩固 |
| 绿色 `stable` | 诊断结果显示 mastered，或该知识点相关计划任务最近完成且近期无新增错题 | 基本稳定 |
| 灰色 `unknown` | 只有笔记/素材，没有错题和练习反馈 | 资料已沉淀，掌握度待验证 |

如果同一节点同时命中多个状态，优先级为：

```text
weak > reviewing > stable > unknown
```

这样可以避免“有笔记就显示掌握”的误导。笔记和素材只能把红色节点推进到黄色，不能单独证明绿色。

### 节点详情

每个知识点详情包含：

- `errors`：最多 5 道相关错题，包含 `error_id`、题干摘要、错题次数、最近错误时间。
- `notes`：最多 5 篇相关笔记，优先错题复盘笔记，显示标题、状态、来源。
- `materials`：最多 5 个已确认或待确认素材，显示确认状态和名称。
- `plan_items`：最多 5 个相关计划任务，显示计划标题、任务状态和完成时间。
- `next_actions`：后端规则生成的 1-3 条行动建议。

行动建议示例：

- 红色且无笔记：`先选 1 道错题整理复盘笔记。`
- 红色且有笔记：`先复看复盘笔记，再做 2 道同类题。`
- 黄色且计划未完成：`把未完成的练习任务补完，完成后再复盘。`
- 绿色：`保持复习频率，一周后再抽查。`
- 灰色：`这部分已有资料，但还缺练习反馈。`

## 后端设计

新增模块：

```text
studybuddy-backend/app/services/learning_map_service.py
studybuddy-backend/app/schemas/learning_map.py
studybuddy-backend/app/routers/learning_map.py
```

### Service

核心函数：

```python
def build_learning_map(db: Session, student_id: int, limit: int = 30) -> LearningMapResponse
```

职责：

1. 读取错题、笔记、素材、计划任务。
2. 按知识点聚合节点。
3. 计算状态和分数。
4. 生成详情引用和下一步建议。
5. 返回前端和 Agent 都能复用的结构。

不得做：

- 不调用 LLM。
- 不写数据库。
- 不读未授权学生数据。
- 不把未确认素材当作高可信内容。

### Router

新增接口：

```text
GET /api/students/{student_id}/learning-map
```

权限：

- 学生只能访问自己。
- 家长只能访问绑定学生。
- 权限复用 `resolve_accessible_student_id`，不在学习地图里重写权限逻辑。

### Schema

建议结构：

```python
class LearningMapResource(BaseModel):
    id: int
    title: str
    type: Literal["error", "note", "material", "plan_item"]
    status: str | None = None
    summary: str = ""
    url: str | None = None

class LearningMapNode(BaseModel):
    tag: str
    status: Literal["weak", "reviewing", "stable", "unknown"]
    error_count: int = 0
    note_count: int = 0
    material_count: int = 0
    plan_item_count: int = 0
    last_wrong_at: str | None = None
    next_actions: list[str]
    resources: list[LearningMapResource]

class LearningMapResponse(BaseModel):
    student_id: int
    generated_at: str
    nodes: list[LearningMapNode]
    summary: dict[str, int]
```

## Agent 设计

现有 `_build_learning_memory_context` 已经读取高频错题、代表性错题、复盘笔记和最近素材。学习地图 MVP 不要复制一套 Agent 逻辑。

推荐做法：

1. `learning_map_service` 提供一个轻量摘要函数：

```python
def summarize_learning_map_for_agent(map_data: LearningMapResponse, limit: int = 5) -> list[str]
```

2. `_build_learning_memory_context` 可以在后续 implementation 中逐步替换部分 `get_blind_spots` 直读逻辑，使用学习地图摘要。
3. 第一版如果改动风险高，可以先保留现有 Agent 上下文，只新增 `query_learning_map` 工具供 Agent 主动查询。

推荐 MVP 采用折中：

- 新增 `query_learning_map` Agent 工具。
- 系统提示补充：当学生问“最近最该补什么 / 我的学习地图 / 哪些知识点薄弱”时优先调用。
- 后续再把 `_build_learning_memory_context` 内部切到 `learning_map_service`。

这样能降低第一版风险，同时为统一口径铺路。

## 前端设计

新增页面：

```text
studybuddy-client/src/pages/LearningMapPage.tsx
studybuddy-client/src/api/learningMap.ts
```

新增路由：

```text
/learning-map
```

学生侧栏放在 `学情诊断` 附近，建议文案为 `学习地图`。

家长端第一版不单独放侧栏；可以从学生详情页后续增加入口。接口先支持家长访问绑定学生，便于后续补入口。

### 页面结构

沿用 `StudentPageShell`：

- 顶部指标：薄弱点、正在巩固、基本稳定、可用资料。
- 主区域：
  - 左侧或上方：知识点节点列表，按状态和错误次数排序。
  - 右侧或下方：选中节点详情。
- 节点样式：
  - 红：需要优先补。
  - 黄：正在巩固。
  - 绿：基本稳定。
  - 灰：资料已沉淀，待验证。

视觉要求：

- 使用现有 CSS token：`--sb-color-error`、`--sb-color-warning`、`--sb-color-success`、`--sb-color-border-secondary` 等。
- 不新增紫蓝渐变、大面积装饰背景或不可读动画。
- 可以用轻微 hover、进场 fade 和节点连线感，但不能影响阅读。
- 卡片半径遵守现有 8-12px 规则，不做过度圆角。

### 交互

1. 默认选中最需要补的知识点。
2. 点击节点切换详情。
3. 详情里每类资源都有明确动作：
   - 错题：去错题本或带到对话复盘。
   - 笔记：打开笔记详情。
   - 素材：打开素材管理。
   - 计划：打开学习计划。
4. 空态引导：
   - 没有错题：去拍题批改或做试卷。
   - 没有笔记：从错题本整理复盘笔记。
   - 没有素材：上传学习图片并确认 Markdown。

## 测试策略

### 后端

- 纯 service 单测：
  - 多道同知识点错题聚合为一个节点。
  - 错题次数高且无笔记时状态为 `weak`。
  - 有错题且有复盘笔记时状态为 `reviewing`。
  - 只有确认素材但无错题时状态为 `unknown`。
  - 计划任务完成且近期无错题时可显示 `stable`。
  - 未确认素材不增加高可信素材计数。
- API 权限测试：
  - 学生只能访问自己。
  - 家长只能访问绑定学生。
  - 未绑定访问返回 403。
- Agent 工具测试：
  - `query_learning_map` 调用 service。
  - 返回摘要不包含不存在的掌握状态。

### 前端

- 页面测试：
  - 加载后显示红黄绿/灰统计。
  - 默认选中最优先节点。
  - 点击节点显示相关错题、笔记、素材和计划。
  - 空态文案能引导下一步。
- 路由测试：
  - `/learning-map` 可进入。
  - 侧栏有 `学习地图`。

### 浏览器验收

1. 登录学生账号。
2. 进入 `学习地图`。
3. 看见知识点状态和统计。
4. 点击一个薄弱知识点。
5. 确认能看到相关错题、复盘笔记、素材或计划反馈。
6. 点击行动入口能去对应页面或带到对话。
7. 回到对话问“我最近最该补什么”，Agent 应优先参考学习地图或同一套错题掌握摘要。

## 文档与发布

实现完成后更新：

- `studybuddy-client/src/data/releaseNotes.ts`
- `docs/已实现能力清单.md`
- `docs/开发进度文档.md`
- `docs/人工验收清单.md`
- `docs/真人验收指南.md`
- 如踩坑，更新 `docs/本地验收踩坑清单.md`

## 风险与处理

| 风险 | 处理 |
|---|---|
| 知识点标签写法不一致，出现重复节点 | 第一版先做 trim、去空、同名去重；复杂同义词合并后续再做 |
| 学生误以为绿色代表永远掌握 | 页面文案写“基本稳定”，不是“永久掌握” |
| 素材未确认却被当作事实 | 只把 `confirmed` 素材作为高可信资源，未确认素材只提示需确认 |
| 页面只有统计没有行动 | 每个节点必须有下一步建议和资源入口 |
| Agent 与页面口径不一致 | 新增 `query_learning_map`，后续逐步把学习记忆上下文切到同一 service |
| 视觉炫技压过内容 | 复用现有 `StudentPageShell` 和 token，先做信息密度高、可扫描的工具页 |

## 实施顺序

1. 后端 schema/service/API。
2. 后端测试和权限测试。
3. Agent `query_learning_map` 工具。
4. 前端 API、路由、侧栏入口。
5. 学习地图页面和前端测试。
6. 帮助更新、文档收口。
7. Codex 浏览器本地验收。
8. 部署上线并用公网 URL 复验。
