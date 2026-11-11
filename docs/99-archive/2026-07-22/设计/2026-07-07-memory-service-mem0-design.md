# 长期记忆适配层与 mem0 接入设计

## 背景

知了的差异化是“学生自己的学习数据 + 家庭督促场景 + 长期记忆教练”。当前 Agent 已能读取画像、错题、笔记、每日回顾和素材列表，但这些读取逻辑分散在 Agent 工具和上下文拼接里。

2026-07-07 已完成两项前置改动：

1. 学习记忆不再依赖白名单关键词触发，默认注入轻量记忆，只跳过登录、账号、帮助和报错等系统类问题。
2. 素材能力从 `read_material` 扩展到 `list_materials + read_material`，Agent 能先知道有哪些素材，再按需读具体内容。

## 外部调研

mem0 Open Source 支持两种运行方式：作为应用内 library 直接 `pip install mem0ai` 使用，或作为自托管 server 运行；自托管 server 默认使用 Postgres + pgvector 作为向量存储。官方文档也说明 library 默认可用本地 Qdrant 和 SQLite history。GitHub README 里当前也把 library、self-hosted server、cloud platform 分成不同使用场景：测试/原型优先 library，团队自托管用 server。

## 设计目标

1. Agent 能跨会话记住学生长期偏好、错题模式、素材摘要和计划习惯。
2. 业务事实仍以 MySQL 表为准：错题、笔记、素材确认稿、计划、回顾不能被 mem0 替代。
3. 记忆必须可追溯：每条记忆保留 `source_type/source_id/student_id/confidence/status`。
4. 记忆必须可纠错：学生或家长否认后可以归档、拒绝或覆盖旧记忆。
5. 第一版避免引入重运维，先做 `memory_service` 适配层，底层可先用 MySQL，后续切换 mem0。

## 推荐架构

```text
Agent loop
  -> memory_service.build_context(student_id, query)
  -> memory_service.search(student_id, query, limit)
  -> memory_service.record_candidate(event)

memory_service
  -> MySQL business tables: error_book / notes / materials / feedback / profile
  -> MySQL memory_events MVP
  -> future adapter: mem0 SDK or self-hosted mem0 server
```

Agent 只依赖 `memory_service` 的稳定接口，不直接调用 mem0 SDK，也不直接拼各业务表细节。

## MVP 范围

### 第一阶段：适配层，不上 mem0 server

- 新增 `memory_service`。
- 读取端聚合现有 MySQL 数据：画像、错题模式、错题复盘笔记、每日回顾、素材列表和素材确认稿摘要。
- 写入端只接收“用户确认后”的记忆候选：画像确认、兴趣确认、错题复盘保存、素材 Markdown 确认、每日回顾保存、计划完成/跳过反馈。
- Agent loop 改为调用 `memory_service.build_context`，逐步替换现在的 `_build_learning_memory_context` 内部拼接。

### 第二阶段：mem0 library 试点

- 在本地或 staging 使用 mem0 library 做语义检索实验。
- 每条写入必须带 metadata：`student_id`、`source_type`、`source_id`、`memory_type`、`status`。
- 对比 MySQL 聚合和 mem0 搜索的命中质量，重点测“最近上传的资料”“总错什么”“我适合怎么学”。

### 第三阶段：评估自托管 server

只有当 library 试点证明有价值，再评估 self-hosted server。否则不要为了“看起来高级”引入 Postgres/pgvector/Neo4j 级别的运维成本。

## 不做什么

- 不把所有聊天原文自动写入长期记忆。
- 不把 AI 未经确认的推断当事实。
- 不用 mem0 替代业务表。
- 不让 Agent 绕过权限 service 直接读跨学生记忆。
- 不把原始素材全文无脑塞进每轮 prompt。

## 验收标准

1. 学生问“你记得我最近上传了什么吗”，Agent 能列素材并说明确认状态。
2. 学生问“我最近总错什么”，Agent 能结合错题、错因和复盘笔记回答。
3. 学生纠正“不是这样”后，旧记忆不再继续污染回答。
4. 家长账号不能读未绑定学生的记忆。
5. mem0 不可用时，系统回退 MySQL 聚合，不影响聊天主流程。
