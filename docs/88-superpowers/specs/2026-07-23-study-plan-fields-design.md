---
title: U-041 学习计划字段扩展与修改 API 设计
date: 2026-07-23
type: spec
status: pending-review
related: docs/99-archive/2026-07-24/学习闭环实施顺序分析-2026-07-22.md
---

# U-041 学习计划字段扩展与修改 API

## 目标

给 `study_plans` 加完整说明字段（description / context_refs / revision），修掉 `create_study_plan` 两次 commit 的空计划风险，新增计划级修改 API + Agent 工具，前端展示 description 并支持手动编辑。

## 背景与现状（基于代码调研）

- `study_plans` 表（`sql/012`）只有 `title` / `focus(256)` / `status` / `planned_date` / `created_by`，**没有完整说明**。AI 创建计划时无法记录「参考了什么错题/素材、学生提了什么要求、为什么这么拆任务」，事后学生和 AI 都只能靠记忆。
- `create_study_plan`（`study_plan.py:97`）**两次 commit**：先 `db.commit()` 写 plan 主记录，再循环 add items 后第二次 `db.commit()`。第二次失败会留下「有计划、没任务」的空计划。
- **无计划级修改函数**：只有 `archive_study_plan`（归档）和 `update_study_plan_item_status`（改单项 status），没有改计划标题/描述/日期的能力。
- Router 无 `PATCH /api/study-plans/{plan_id}`。
- 前端 `TodayPlanPanel` 不展示 `focus`/`description`；`ManualStudyPlanDrawer` 手动创建时 `focus=null`，无 description 输入。

## 设计

### 1. 数据层

`study_plans` 加三字段（迁移 `sql/021`，幂等执行靠 `scripts/ensure_study_plan_fields.py`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `description` | TEXT NULL | 计划完整说明：AI 参考了什么、学生要求什么、为什么这么拆任务 |
| `context_refs` | JSON NULL | 来源上下文引用（历史计划/素材/错题/回顾 id 等） |
| `revision` | INT NOT NULL DEFAULT 1 | 乐观锁版本号，每次修改 +1 |

**`focus` 保留**作短目标摘要，不废弃；`description` 是完整说明。两者职责不同。

### 2. Service（`study_plan.py`）

- `create_study_plan` 加 `description` / `context_refs` 入参；**改单事务**：`db.flush()` 拿 `plan.id`（不单独 commit），items 一起 `db.commit()`，任一失败整体回滚。
- `_to_plan` 转换加 `description` / `context_refs` / `revision`。
- 新增 `update_study_plan(db, plan_id, *, title, description, planned_date, revision)`：
  - `revision` 必填，乐观锁校验：`plan.revision != revision` 抛 `ValueError`（计划已被改过，请刷新）
  - 只改传入的非 None 字段
  - 校验通过后 `revision + 1`，单 commit

### 3. Router（`router.py`）

- `POST /students/{id}/study-plans`（create）传 `description` / `context_refs`
- 新增 `PATCH /api/study-plans/{plan_id}`：传 `UpdateStudyPlanRequest`（title/description/planned_date 可选 + revision 必填）；revision 冲突返 **409 Conflict**；权限校验复用 `resolve_accessible_student_id`

### 4. Agent 工具

- 新增 `_TOOL_UPDATE_STUDY_PLAN` schema（`plan_id` + `revision` 必填，`title`/`description`/`planned_date` 可选），注册进 `ALL_TOOLS` + `STUDENT_TOOLS`
- handler `_handle_update_study_plan`（`handlers/learning.py`）：调 `study_plan.update_study_plan`，revision 冲突返 `{"error": ...}`
- `handlers/__init__.py` + `agent_loop.py` 注册 re-export（满足 `test_all_tools_have_handlers` 硬约束）
- prompt 提及 `update_study_plan` 用法（学生想改计划时调用，需带 revision）

### 5. 前端

- `types/p2.ts`：`StudyPlan` interface 加 `description` / `context_refs` / `revision`
- `features/p2/api.ts`：`createStudyPlan` 加 description/context_refs 参数；新增 `updateStudyPlan(planId, payload)`
- `TodayPlanPanel.tsx`：展示 description（可折叠）
- `ManualStudyPlanDrawer.tsx`：表单加 description 输入

## 决策（用户已认可）

1. `focus` 保留作短摘要，新增 `description` 放完整说明
2. `revision` 整数乐观锁（不用 updated_at，语义清晰）
3. DB 迁移 021（线上 ALTER，幂等 ensure 脚本）
4. 修改入口两个都要：AI 调 `update_study_plan` 工具 + 手动抽屉编辑

## 验收标准

- 新建计划可带 description，落库后 Today 可展开查看
- 修改计划标题/描述/日期后 Today 立即同步，单事务（无空计划风险）
- revision 冲突返 409，不覆盖
- `create_study_plan` 改单事务后，items 写入失败不留空计划（测试验证）
- AI 调 `update_study_plan` 工具修改计划（live 测试验证 AI 会调）
- typecheck / lint / 后端 pytest / 前端 vitest 全过

## 不做

- 不改任务项（任务项状态用现有 `update_study_plan_item_status`）
- 不改 `status` 枚举
- 不做复杂 diff / 版本历史
- 不改 `focus` 语义
- 不做任务项的增删改（U-042 范围）

## 风险

- 线上 DB ALTER：用幂等 `ensure_study_plan_fields.py`，部署时 `deploy_backend.sh` 调用
- `update_study_plan` 工具 AI 可能漏传 revision：handler 校验拒绝，返 error 提示
- 与 U-043 PR（`feat/present-choice-question`）合并时 `tools.py` / `agent_loop.py` / `handlers/__init__.py` 同区域有文本冲突（都是加工具注册），rebase 解决，逻辑不冲突

## 与 U-043 的关系

U-041 **不依赖** U-043（计划修改不碰选择按钮）。基于 main 独立做。合并时同区域文本冲突是良性的（加不同工具），rebase 解决。
