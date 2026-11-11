# ADR-0003: agent_loop 作为跨域编排层，留 core/agent

- 状态：accepted（第一步保守，待域稳定后复评）
- 日期：2026-07-19
- 关联：`archive/2026-07-22/设计/后端模块化架构.md` §5、§7.1，`archive/2026-07-22/需求/13-后端按业务功能模块化拆分.md` §7.1

## 背景

`app/core/agent_loop.py`（2814 行）是 Agent 工具分发枢纽，import 了几乎全部 service，且大量用函数内延迟 import（`agent_loop.py:1105/1177/1248/1774…`）回避循环依赖。这是已暴露的「我牵太多」信号。它跨所有业务域，不属于任何单一功能。

## 决策

`agent_loop` 作为跨域编排层（Application Layer / Orchestrator），留在 `core/agent/`，**不**拆进任何单一 feature。它是唯一允许跨所有 feature service 的模块。第一步保守不拆散，等各 feature 迁移稳定后再复评是否把工具 handler 按归属域下沉。

## 放弃的方案

- **工具 handler 下沉到各 feature**（`_handle_query_diagnosis` 进 `learning/`、`_handle_save_note` 进 `note/`…，agent_loop 只剩分发骨架）：最干净，但工作量大、风险最高，域边界还没稳定时做容易反复。留作模块化完成后的二期选项。

## 影响

- `agent_loop` 留 `core/agent/`，依赖各 feature service 的公开函数。
- feature 之间不通过 agent_loop 交互，只通过对方 service 公开接口。
- 模块化第一阶段不碰 agent_loop，降低迁移风险。
