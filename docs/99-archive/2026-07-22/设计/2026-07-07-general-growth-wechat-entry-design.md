---
title: 通用成长目标与微信轻入口设计
date: 2026-07-07
type: spec
status: ready_for_review
source_requirement: docs/requirements/06-通用成长目标与微信轻入口.md
---

# 通用成长目标与微信轻入口设计

## 背景

智学伴现在已经能处理学科计划、错题、笔记、素材、学习地图和家长督促。但学生也会提出非学科目标，例如“我要健身”“我想练口才”“我想自律”。这些不是数学、英语题目，却属于长期成长教练场景。

这类需求不应该新建一套角色系统，也不应该靠继续堆 prompt 硬编码。当前项目已经有可复用能力：

- `study_plan_confirmation_service`：计划必须先给草案，再由学生确认。
- `p2_service.save_profile_onboarding`、`record_interest`、`update_attributes`：画像、兴趣和学习属性已有基础。
- `agent_loop` 工具注册器：工具 schema 和 handler 已集中管理。
- 素材、错题、笔记、学习地图：已经是 Agent 可读取的学生资产。
- `docs/学生记忆与微信接入需求文档.md`：已经定义微信是轻入口，不能复制业务系统。

## 目标

第一版只解决两个问题：

1. 学生提出非学科成长目标时，Agent 能识别为 `general_growth` 或 `interest_exploration`，先问清目标、限制和可用时间，再给低风险草案。
2. 微信入口先做架构 adapter 设计，让微信文本、图片最终进入同一套 Agent、素材和错题流程，不复制一套微信专属业务逻辑。

## 非目标

- 不做心理咨询、医疗建议、运动处方。
- 不做高强度训练计划或身体评估。
- 不做完整微信公众号后台、消息推送运营系统。
- 不把微信当成第二套网页。
- 不绕过学生确认写长期画像、兴趣或计划。

## 方案对比

### 方案 A：继续在系统 prompt 里加规则

优点：实现最快。

缺点：不可测试，容易和学科计划规则混在一起；规则越多越难定位为什么 Agent 回答跑偏。

### 方案 B：轻量意图分类服务 + Agent 策略注入

做法：

- 新增 `growth_intent_service`，用规则优先的方式分类：
  - `academic_learning`
  - `general_growth`
  - `interest_exploration`
  - `wellbeing_boundary`
  - `system_or_account`
- 分类结果只作为策略提示，不替代 LLM 回答。
- 对 `general_growth` 复用学习计划确认机制：没有确认不能创建计划。
- 对 `wellbeing_boundary` 输出安全边界，建议找家长或专业人士，不提供高风险方案。

优点：可单测、可解释，MVP 足够轻。

缺点：第一版分类准确率有限，仍需真实对话样本迭代。

### 方案 C：接入完整意图识别/记忆框架

优点：长期可扩展。

缺点：当前会引入额外部署和调试成本，不适合家庭内测阶段。

## 选择

采用 **方案 B：轻量意图分类服务 + Agent 策略注入**。

原因：

- 符合“不重复造轮子”：复用计划确认、画像、兴趣、素材和 Agent 入口。
- 符合“不硬编码到页面或 prompt”：分类规则集中在服务层，可测试、可替换。
- 符合“先小而真实”：先让“我要健身/练口才/自律”这类真实输入不跑偏。

## 领域模型

### GrowthIntent

```python
class GrowthIntent(BaseModel):
    intent: Literal[
        "academic_learning",
        "general_growth",
        "interest_exploration",
        "wellbeing_boundary",
        "system_or_account",
        "unknown",
    ]
    confidence: float
    matched_signals: list[str]
    safety_level: Literal["normal", "needs_guardrail", "blocked"]
    strategy_hint: str
```

### 分类规则

| 输入信号 | 分类 | 策略 |
|---|---|---|
| 数学、英语、错题、背单词、语法 | `academic_learning` | 走现有学习计划/错题/笔记流程 |
| 健身、跑步、力量、减肥 | `general_growth` 或 `wellbeing_boundary` | 先问年龄、目标、身体限制；只给低强度建议 |
| 口才、表达、演讲、自律、习惯 | `general_growth` | 先问场景和可用时间，再给草案 |
| 喜欢、兴趣、想学某爱好 | `interest_exploration` | 学生自己决定兴趣，家长不审批 |
| 疼痛、受伤、极端减重、药物、心理危机 | `wellbeing_boundary` | 不给方案，引导告诉家长或专业人士 |
| 登录、账号、帮助、报错 | `system_or_account` | 不写记忆，不创建计划 |

## Agent 行为

### 通用成长目标

学生说“我要健身”时，Agent 不应直接安排训练计划。第一轮应询问：

- 目标是什么：体能、习惯、减脂、体育考试、放松。
- 每天/每周可用时间。
- 有没有不舒服、受伤、家长或学校要求。

如果学生已经给出足够信息，Agent 可以给“计划草案”，但仍需问“这样可行吗”。只有学生明确确认，才能调用 `create_study_plan`，并且 `confirmed=true`。

### 兴趣探索

兴趣属于学生自己。Agent 可以记录学生确认的兴趣，也可以建议下一步尝试，但不能要求家长审批兴趣。

### 安全边界

健身和身心健康相关内容必须保守：

- 不给高强度训练、极端饮食、药物建议。
- 不诊断疾病。
- 出现疼痛、受伤、明显心理危机时，建议告诉家长并联系专业人士。

## 微信轻入口设计

第一版只做 adapter 设计，不接真实微信平台。

```text
WeChat message
  -> wechat_adapter.normalize()
  -> ChatInboundMessage(text, images, user_binding)
  -> existing chat agent endpoint/service
  -> existing material/error-book route for images
  -> web deep link for complex confirmation
```

### 文本

微信文本最终进入同一套 Agent session。业务逻辑仍在 Agent 和 service 层，不在微信 adapter 里判断“怎么学习”。

### 图片

微信图片只做入口转换：

- 如果用户说“批改/错题/作业”，进入拍题候选。
- 如果用户说“素材/资料/单词表”，进入素材候选。
- 不确定时让用户选择“拍题批改”或“上传素材”。

确认 Markdown、逐题修正、计划确认等复杂操作跳转网页。

## 前端体验

MVP 不新增大型页面。只在聊天体验里体现：

- “我要练口才”时，Agent 先追问目标和场景。
- “我要健身”时，Agent 给低风险、短时间、可确认的草案。
- 帮助与更新新增一条说明：支持非学科成长目标的第一步。

## 测试

### 单测

- `classify_growth_intent("我想练口才")` 返回 `general_growth`。
- `classify_growth_intent("我要健身")` 返回 `general_growth`，且 `safety_level` 至少是 `needs_guardrail`。
- `classify_growth_intent("我膝盖疼还想每天跑十公里")` 返回 `wellbeing_boundary`。
- 学科输入不被误判为成长目标。
- 登录/报错输入不触发记忆或成长计划。

### Agent 行为测试

- “我想练口才”不会直接创建计划，而是追问目标、场景和时间。
- 用户确认草案后才允许创建计划。
- “我想健身，膝盖疼”不会给训练计划。

### 浏览器验收

1. 登录学生账号。
2. 输入“我想练口才”。
3. 确认 Agent 先问场景和目标，而不是直接创建计划。
4. 输入“我每天练 10 分钟，主要想上课回答问题更清楚”。
5. 确认 Agent 给计划草案，并询问是否可行。
6. 回复“可以，按这个创建”。
7. 确认计划创建成功，且计划内容是低风险、短任务。

## 验收风险

| 风险 | 防护 |
|---|---|
| 分类规则过窄 | 记录真实对话样本，后续扩展词表或接 LLM 分类 provider |
| Agent 绕过确认直接建计划 | 后端继续用 `study_plan_confirmation_service` 拦截 |
| 健身建议过度 | 单测覆盖危险输入，prompt 和策略提示都强调安全边界 |
| 微信入口复制业务逻辑 | adapter 只做 normalize 和路由，不处理学习业务 |
| AI 自嗨写画像 | 只有学生明确确认后才写兴趣、画像或计划 |

## 实施顺序

1. 新增 `growth_intent_service` 和单测。
2. 在 Agent loop 进入模型前注入简短策略提示，避免继续扩大系统 prompt。
3. 复用计划确认拦截，补 Agent 行为测试。
4. 更新帮助、需求、真人验收清单。
5. Codex 浏览器验收学生聊天路径。

## 用户审核点

请重点确认：

1. 第一版只做“成长目标识别 + 稳妥追问 + 计划确认”，是否足够。
2. 微信第一版只做 adapter 设计、不接真实微信平台，是否符合当前节奏。
3. 健身/口才/自律是否都按“先问清楚，再给草案，再确认”的流程走。
