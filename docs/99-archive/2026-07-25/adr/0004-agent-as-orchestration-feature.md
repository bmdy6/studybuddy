# ADR-0004: Agent 模块复评——features/agent/ 作为顶层编排 feature

- 状态：accepted
- 日期：2026-07-21
- 关联：supersedes ADR-0003；ADR-0001（agent_loop 留 core/agent/ 决策）；`docs/架构.md`（单向依赖）
- 关联文档：`archive/2026-07-22/设计/后端模块化架构.md` §7.1

## 背景

ADR-0003 决定 `agent_loop` 留 `core/agent/`，状态标注"第一步保守，待域稳定后复评"。截至本 ADR，各 feature 迁移已稳定（PR #56–#71），PR #68 已把 `agent_loop.py`(2817L) 拆为 `features/agent/` 子模块：

| 文件 | 行数 | 职责 |
|---|---|---|
| `features/agent/agent_loop.py` | 394 | 分发骨架 |
| `features/agent/context.py` | 628 | 对话上下文 |
| `features/agent/tools.py` | 688 | 工具注册 |
| `features/agent/prompts.py` | 121 | 提示词 |
| `features/agent/handlers/` | - | 工具 handler 子目录 |

`chat` 同期落在 `features/chat/`（agent/context/router/schemas/sessions）。`core/agent/` 目录从未创建。

## 决策

复评结果：**保留 `features/agent/` + `features/chat/`，不回退到 `core/agent/`**。

理由：
1. **单向依赖**（架构.md）：agent 调用几乎所有 features（p2/growth/materials/learning/exams…）。若 agent 在 `core/`，则 `core` 反向依赖 `features`，违反单向依赖。`features/agent/` 作为**顶层编排 feature**，向下依赖各 features + core，单向成立。
2. **内聚**：agent 是"跨域编排"应用层，不属任何单一 feature，但也不是底层基础设施（core 是稳定底层：auth/infra）。`features/` 作为应用层承载编排最合适。
3. **与 ADR-0003 的延续**：ADR-0003 放弃的"工具 handler 全下沉到各 feature"是最激进选项（风险高）。#68 的拆分（骨架 + handlers 子目录）是中间形态——保留编排集中性的同时模块化，可平滑演进到二期全下沉。

## 放弃的方案

- **回退 `core/agent/`**：违反单向依赖，需返工 #68；且 ADR-0003 本就预留复评。
- **工具 handler 全下沉到各 feature**：ADR-0003 已评估，风险高，留二期。

## 影响

- `core/agent/` 不创建。ADR-0001 §4.2 与 ADR-0003 的 `core/agent/` 定位由本 ADR 取代。
- `features/agent/` 是顶层编排 feature，允许依赖各 features + core；其他 feature 之间不通过 agent 交互（沿用 ADR-0003 约束）。
- `features/chat/` 同理（chat 是 agent 对话的呈现层）。
- 后续 `study_plan_confirmation_service` 归 `features/agent/`（agent 编排依赖，清掉 `app/services/` 残留）。
