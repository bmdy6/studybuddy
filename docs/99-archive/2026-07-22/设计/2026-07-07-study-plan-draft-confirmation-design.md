---
title: 学习计划草案确认设计
date: 2026-07-07
type: spec
status: draft
---

# 学习计划草案确认设计

## 背景

需求来源：`docs/requirements/01-学习计划草案确认.md`。

当前系统已经有一层保护：

- Agent 系统提示要求粗略意图不能直接创建计划。
- `create_study_plan` 工具要求 `confirmed=true`。
- `agent_loop._is_study_plan_confirmed()` 会检查最近用户回复和上一轮助手草案。
- 每日回顾的未完成目标已经能带入对话，prompt 包含“先商量再创建”。
- `p2_service.create_study_plan()` 已是正式落库入口，计划列表、逾期提醒、任务完成/跳过都复用它。

问题是确认逻辑仍散在 `agent_loop.py`，缺少清晰可测试的“计划草案确认”边界；草案有效期也没有产品化，容易让旧对话里的“可以”被误当成当前计划确认。

## 目标

1. 学生或家长只表达粗略意图时，Agent 只能追问或给草案，不能落库计划。
2. 用户明确确认最近的计划草案后，才允许调用正式 `create_study_plan`。
3. 草案确认有短有效期，过期后需要重新确认。
4. 每日回顾目标进入对话时，继续使用同一套确认规则。
5. 实现时先抽通用逻辑，不在 Agent loop 里继续堆硬编码。

## 非目标

- 不做复杂日历排程。
- 不做跨设备草案管理页面。
- 不新增完整“计划草案表”作为第一版。
- 不把计划草案展示做成单独页面。
- 不改变已有正式学习计划 API 的基本返回结构。

## 架构检查结论

### 后端现状

| 文件 | 现状 | 设计取舍 |
|---|---|---|
| `app/core/agent_loop.py` | 包含系统提示、工具定义、`_is_study_plan_confirmed`、工具执行 guard | 抽出计划确认判断，Agent loop 只调用服务函数 |
| `app/services/p2_service.py` | 已有正式计划创建、查询、逾期归档、提醒和任务状态更新 | 继续作为唯一正式计划 service，不复制创建逻辑 |
| `app/models/p2.py` | `StudyPlan.status` 只有 `active/completed/archived` | 第一版不扩状态，避免影响现有页面和 API |
| `app/schemas/p2.py` | 已有 `StudyPlanItemDraft` 但没有使用草案模型 | 可复用命名思想，但不直接新增未落库 API |
| `tests/unit/test_agent_loop.py` | 已有粗略意图不落库、确认后创建等测试 | 扩充草案有效期和确认判断单测 |

### 前端现状

| 文件 | 现状 | 设计取舍 |
|---|---|---|
| `DailyReviewPage.tsx` | `buildGoalPlanPrompt()` 已把目标带到对话并要求先商量 | 保持入口，必要时只微调文案 |
| `StudyPlansPage.tsx` | 展示正式计划、逾期复盘、完成/跳过 | 不新增复杂草案页；如果有提示，用现有页面 shell 和 token |
| `releaseNotes.ts` / `HelpPage.tsx` | 已有帮助更新机制 | 完成后补本次更新说明 |
| `index.css` / `designTokens.ts` | 使用暖米色背景、青绿色主色、低饱和状态色 | 新增样式必须用 `--sb-*` token，不直接用 AntD 默认蓝/橙/绿做普通信息标签 |

## 设计方案

### 1. 抽出 `study_plan_confirmation_service`

新增后端服务：

`studybuddy-backend/app/services/study_plan_confirmation_service.py`

职责：

- 判断最近用户消息是否是确认。
- 判断最近助手消息是否包含计划草案。
- 判断草案是否仍在有效期内。
- 返回结构化结果，说明是否允许创建、失败原因和下一步提示。

建议接口：

```python
@dataclass(frozen=True)
class StudyPlanConfirmationResult:
    allowed: bool
    reason: str
    next_step: str

def validate_study_plan_confirmation(
    messages: list[dict[str, Any]],
    now: datetime | None = None,
    ttl_minutes: int = 30,
) -> StudyPlanConfirmationResult:
    return StudyPlanConfirmationResult(
        allowed=False,
        reason="需要先给出计划草案并得到用户确认。",
        next_step="请先询问学习目标、可用时长、内容偏好，给出计划草案并等待用户确认。",
    )
```

`agent_loop.py` 不再直接维护一坨正则和草案 marker，只调用该服务。

### 2. 草案有效期

第一版不新增草案表，理由：

- 当前聊天消息本身就是草案协商发生的位置。
- 已有 guard 是基于最近消息判断。
- 需求重点是避免“旧确认误执行”，不是做草案管理台。

有效期规则：

- 默认 30 分钟。
- 如果消息里没有可靠时间戳，则只能允许“最近一轮助手草案 + 最近一轮用户确认”的短链路。
- 如果消息有 `created_at` / `timestamp` / `time` 字段，则使用时间判断。
- 超过有效期返回 `allowed=False`，提示重新确认当前计划草案。

### 3. 确认判断语义

允许：

- “可以”
- “确认”
- “就这样”
- “按这个”
- “创建吧”
- “安排吧”

不允许：

- “下午要学英语”
- “帮我学数学”
- “可以帮我看看吗”
- “直接创建一个计划”但前面没有近期草案

如果用户明确说“直接创建”但没有草案，仍不落库，改为要求先给草案。

### 4. Agent 工具 guard

`create_study_plan` 工具执行前继续做服务端 guard：

```python
if name == "create_study_plan":
    result = validate_study_plan_confirmation(messages)
    if not args.get("confirmed") or not result.allowed:
        output = {
            "error": result.reason,
            "saved": False,
            "next_step": result.next_step,
        }
```

这样即使模型幻觉调用工具，也不能越过后端逻辑。

### 5. 前端体验

第一版尽量不新增 UI 面积：

- 每日回顾的“商量计划”入口继续跳到对话页。
- 对话页工具卡片继续展示 `create_study_plan` 的结果。
- 学习计划页只展示正式落库计划，不展示未确认草案。
- 如果后续需要显示草案，再做工具卡片专门样式。

样式规则：

- 普通信息标签不要用 AntD `blue`。
- 计划草案/确认提示优先使用 `--sb-color-bg-primary-soft`、`--sb-color-primary-deep`、`--sb-color-border-primary-soft`。
- 警告/过期仍使用项目 warning token，不直接堆默认 `orange`。

## 可抽离通用逻辑

本次优先抽：

1. **计划确认判断**：从 `agent_loop.py` 移到 `study_plan_confirmation_service.py`。
2. **时间解析辅助**：支持从消息 dict 中读取 `created_at`、`timestamp`、`time`。
3. **草案 marker 和确认短语**：集中在服务文件内，便于测试和扩展。

本次暂不抽：

- 通用 Agent 工具 guard 框架。当前只有学习计划有这类强确认需求；等笔记/画像/素材确认也沉淀出同类模式后再抽。
- 前端计划卡片组件。`StudyPlansPage.tsx` 虽然偏大，但本次需求的 UI 改动很轻，先不做无关拆分。

## 数据与权限

- 正式计划仍由 `p2_service.create_study_plan()` 创建。
- 权限仍由 `_resolve_tool_student_id()` 和 router 的 `_student_id()` 处理。
- 不新增表，不新增迁移。
- 不改变 MySQL 结构。

## 测试计划

### 后端单测

新增：

- `tests/unit/test_study_plan_confirmation_service.py`

覆盖：

- 粗略意图无草案时不允许。
- 助手刚给草案，用户确认时允许。
- 用户确认但草案超过 30 分钟时不允许。
- 用户说“直接创建”但无近期草案时不允许。
- 无时间戳时只允许最近一轮草案 + 最近一轮确认的短链路。

扩展：

- `tests/unit/test_agent_loop.py`

覆盖：

- 模型误调 `create_study_plan` 且前序草案过期时不落库。
- 每日回顾带来的 prompt 不绕过确认。

### 前端单测

如只改每日回顾 prompt 文案，扩展：

- `DailyReviewPage.test.tsx`

确认 prompt 仍包含：

- “请先和我商量”
- “确认学习时长、任务拆分和可行性”
- “再帮我创建学习计划”

如果不改前端代码，本次不新增前端测试。

### 浏览器验收

本地：

1. 登录学生账号。
2. 进入对话页。
3. 输入“下午要学英语”。
4. 观察不会直接创建计划，应先追问或给草案。
5. 回复“可以，就按这个来”。
6. 确认学习计划页出现正式计划。
7. 从每日回顾未完成目标点击“商量计划”，确认仍走同一流程。

线上：

- 部署后用公网 URL 重复关键路径。

## 文档与踩坑

完成后必须更新：

- `docs/开发进度文档.md`
- `docs/已实现能力清单.md`
- `docs/人工验收清单.md`
- `studybuddy-client/src/data/releaseNotes.ts`

如果遇到以下问题，记录到 `docs/本地验收踩坑清单.md`：

- 本地 MySQL 3307 未启动导致验收失败。
- Agent 又绕过确认直接创建计划。
- 草案有效期使用了硬编码日期。
- 浏览器验收中测试数据污染正式账号。

## 风险

| 风险 | 应对 |
|---|---|
| 正则误判“可以” | 必须同时要求近期助手草案存在 |
| 无消息时间戳无法判断 TTL | 降级为最近一轮短链路，不允许跨多轮旧确认 |
| 模型继续说“已创建”但工具被 guard 拦住 | 工具结果包含 `saved=false` 和下一步提示，后续回复要求按工具结果说明 |
| 过度设计草案表 | 第一版不建表，只抽确认服务 |

## 用户验收点

- 计划像商量出来的，而不是 AI 强行安排。
- 学生可以修改或拒绝草案。
- 旧对话里的“可以”不会触发新计划。
- 每日回顾目标进入对话后也不绕过确认。
