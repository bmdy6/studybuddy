# 对话式冷启动画像与 AI 静默更新 方案

> 日期：2026-07-18　分支建议：`feat/conversational-profile-onboarding`（从最新 `origin/main` 拉）

## 1. 背景与目标

当前冷启动画像走「横幅 → `ProfilePage` 表单让用户自己填」。问题：摩擦大（手机端打字）、与对话割裂、`save_profile_onboarding` 每次还写一条 `learning_feedback`（重复调用堆重复反馈）。

目标：把冷启动改成 **AI 对话式 + 选项化（chips）+ AI 静默增量更新**：

- 冷用户进入时，AI 主动（触发门控下）一次问一个画像字段，给可点选项，用户点 chips 即可，不必打字；开放字段（学校/区县）才回退手填。
- 画像在后续对话里持续演进：用户**明确陈述**的事实 → AI 静默调 `update_profile` 落库；AI **推断**的 → 不静默写，转成一道确认题（走同一套 chips）。
- 横幅降级为带持久 snooze 的轻提示，主路径是 agent 对话。

渠道约束：主渠道是手机端 web（微信内置浏览器打开），将来做小程序。chips 作为主交互（web 可渲染、小程序可平移），「回复数字」作为兜底契约（chips 失效 / `wechat_bot_service` 文本通路仍可用）。

## 2. 设计原则（已与用户确认）

1. **静默写规则**：明确陈述 → 静默写；推断 → 转确认题，不静默写。
2. **混合选项化**：可枚举字段（年级/学期/偏好时段/薄弱科目）走 chips；开放字段（学校/区县）走「其他/手动输入」兜底。
3. **证据制不变**：`update_profile` 只动画像字段（grade/semester/school/district/textbook/weak_subjects/preferences/兴趣增删），**不碰能力分与 `subject_sources`**（能力分仍只由大考/微调驱动）。
4. **读后再问**：AI 问前先看 `get_profile_summary` 的 `missing_fields`，只问缺的，不重复问。
5. **触发门控**：仅冷用户（`needs_onboarding=true`）+ 首次问候 / 语义偏冷启动 / 不知从何开始 时主动问；带具体问题来的先答疑再顺手带一个。

## 3. 后端改动

### 3.1 新工具 `update_profile`（核心，静默增量落库）

- **schema**（`app/schemas/p2.py`）：新增 `UpdateProfileRequest`，所有字段可选：
  `grade/semester/school/district/textbook_versions/recent_scores/weak_subjects/study_preferences` + `add_interests: list[str]` + `remove_interests: list[str]`。
- **service**（`app/services/p2_service.py`）：新增 `update_profile(db, student_id, req, actor_role) -> ProfileSummary`
  - 复用 `_latest_snapshot_dict` 拿最新快照，**只覆盖传入字段**（增量、幂等）。
  - 兴趣：`add_interests` 走 `add_interest`（已按 tag 去重）；`remove_interests` 按 tag 删。
  - **不写 `learning_feedback`**（去掉 onboarding 的 feedback 副作用）。
  - `subject_sources` / 能力分 / `mastered_count` 保持不动。
  - 返回 `get_profile_summary` 让 AI 看到最新状态。
- **handler**（`app/core/agent_loop.py`）：新增 `_handle_update_profile`，照 `_handle_save_profile_onboarding`（`agent_loop.py:2027`）写；`sid = _resolve_tool_student_id(...)`。
- **工具定义**：在 tools 列表加 `update_profile` 描述，强调「对话中学到明确事实时静默调用，增量幂等，不写反馈，不动能力分」。
- **注册**：`_HANDLERS`（`agent_loop.py:~2700`）加 `"update_profile": _handle_update_profile`。
- **工具可用范围**：student 角色可调（画像演进主发生在学生侧）；teacher 角色辅导时也可调（用 `student_id`）。

### 3.2 新工具 `present_profile_question`（chips 交互载体）

- **schema**：`{field: str, question: str, options: list[{label, value}], allow_other: bool}`。
- **handler** `_handle_present_profile_question`：**纯展示型**，不做落库。返回 `{"asked": true, "field", "options", "allow_other"}`，并把 `question` 作为提示返回。
- **工具定义描述**强调：调它 = 向学生提问一次问一个字段；可枚举字段给 3-5 个选项 + 必要时「其他」；**调用后下一轮只输出问题文本、不再调工具、等学生回答**（自然结束本轮，无需特殊「终止工具」逻辑——见 §6 风险）。
- **注册**：加入 `_HANDLERS` 与工具列表。
- 前端依据该工具调用的 `input` 渲染 chips（见 §4.1）。

### 3.3 调整强制 onboarding 兜底（`agent_loop.py:1401`）

- `_forced_profile_onboarding_tool` 现在强制 `save_profile_onboarding`。改为：当从自由文本（打字 / 「回复数字」兜底）抽到画像信号时，强制调 **`update_profile`**（增量、无 feedback 副作用），而不是整批 `save_profile_onboarding`。
- chips 回答的落库由 LLM 直接调 `update_profile` 驱动（AI 自己问的，上下文最清楚），不靠强制。
- `_extract_profile_onboarding_args`（`agent_loop.py:1366`）基本复用，输出对齐 `UpdateProfileRequest`。

### 3.4 `save_profile_onboarding` 副作用清理

- `p2_service.save_profile_onboarding`（`p2_service.py:639`）删掉 `submit_feedback("冷启动学习偏好：...")` 那一行——重复调用会堆重复反馈，且该反馈未被错因展示消费。
- 该工具保留：表单/设置页「编辑画像」仍直连其 API（不经 agent）。

### 3.5 agent prompt 改动（`agent_loop.py` system_prompt 第 9 条画像段 + `_build_profile_context`）

- 冷启动指令改为：冷用户首次问候 / 不知从何开始时，**一次问一个**缺失字段，调 `present_profile_question` 给 chips；可枚举字段给选项，开放字段给「其他」。
- 静默写规则写进 prompt：明确陈述 → `update_profile` 静默落库；推断 → 转 `present_profile_question` 确认题，不直接写。
- 收齐后用自然语言复述确认，不再重复问。
- 现有「不要只调 record_interest/get_attributes 替代画像保存」改成「优先 `update_profile` 增量更新；`save_profile_onboarding` 仅整批首存用」。

## 4. 前端改动（`studybuddy-client`，手机端 web）

### 4.1 chips 渲染（`src/pages/chat/MessageBubble.tsx`）

- 新增 `ProfileQuestionCard`：当 `msg.tools` 里某 tool `name === 'present_profile_question'` 时，渲染 `question` + 可点 chips（label）。点 chip → 调 `handleSend(option.value)`（复用 `ChatPage.tsx:472` 的 override 范式，见 `:652/:707/:759`）+ 置灰该组 chips（防重复点）。
- `allow_other=true` 时多一个「其他」chip → 点击聚焦输入框让用户手打（开放字段兜底）。
- `TOOL_LABELS`（`MessageBubble.tsx:37`）加 `present_profile_question: '选择'`、`update_profile: '更新画像'`（update_profile 建议静默工具，前端可弱展示或折叠，避免每条都冒卡片）。
- SSE 事件链不变：现有 `tool_call` 事件已带 `{name, input, id}`，chips 直接读 `input`。

### 4.2 横幅降级 + 持久 snooze（`src/pages/ChatPage.tsx:1017`）

- 保留「学习画像待补全」横幅但降为更轻量，主入口仍是 agent 对话。
- `profilePromptDismissed` 从 `useState` 改为 `localStorage` 持久 snooze（如关 7 天 / 问够 N 次后不再弹），避免反复骚扰。

### 4.3 表单降级为「编辑画像」设置页（`src/pages/ProfilePage.tsx`）

- `ProfilePage` 保留为事后编辑入口（完整字段、直接调 `saveProfileOnboarding` API），不再当冷启动主入口。
- 横幅「补全学习画像」按钮文案改「编辑画像」/ 仍可跳 `#/profile`。

## 5. 兼容与数据

- `StudentAttribute.snapshot` 结构不变，`update_profile` 复用现有字段键。
- `subject_sources` 向后兼容逻辑（`_normalize_snapshot_sources`）不动。
- 旧 `save_profile_onboarding` 写过的 feedback 数据保留，仅停止新增。
- 无 DB 迁移。

## 6. 风险与对策

- **`present_profile_question` 不终止本轮**：按现有 loop，工具执行后进入下一轮 LLM 生成。靠 prompt 约束「调用后下一轮只输出问题文本、不再调工具」自然结束（`agent_loop.py:1573` 无 tool_use 即 break）。若 LLM 偶发多调一轮，可接受；严重时再考虑特殊「terminal tool」处理。
- **AI 推断误写**：靠 §2 规则 1（推断转确认题）+ prompt 强约束；`update_profile` 仅落明确陈述值。
- **chips 与文本重复提问**：agent 文本回复 + chips 同时出现时，chips 是交互主体，文本是友好措辞，可接受；如冗余可在 `ProfileQuestionCard` 内不重复显示 question 文本。
- **打字兜底**：用户不点 chip 直接打「初二」/「2」→ `_forced_profile_onboarding_tool`（已改指 `update_profile`）兜底落库。

## 7. 测试

- 后端单测（`tests/unit/test_p2_service.py` / `test_agent_loop.py`）：
  - `update_profile` 增量覆盖、兴趣去重增删、不写 feedback、不碰 subject_sources、返回最新 summary。
  - `present_profile_question` 返回展示结构、不落库。
  - 强制 onboarding 改指向 `update_profile`。
- 后端 API 测试（`tests/api/test_p2.py`）：`update_profile` 经路由可用、权限（student/teacher）。
- 前端测试（`ChatPage.test.tsx`）：chips 渲染、点击触发 `handleSend`、置灰防重复；`ProfilePage.test.tsx`：编辑画像仍可用。

## 8. 实施顺序

1. 后端 `update_profile`（schema + service + handler + 注册 + 工具定义）+ `save_profile_onboarding` 去副作用 + 单测。
2. 后端 `present_profile_question`（schema + handler + 注册 + 工具定义）+ prompt 改动 + 强制兜底改指向 + 单测。
3. 前端 `ProfileQuestionCard` chips 渲染 + 点击发消息 + 置灰。
4. 前端横幅降级 + 持久 snooze + 表单文案改「编辑画像」。
5. 联调：冷用户首次问候 → chips 问答 → 静默落库 → 后续对话推断转确认题。
6. 验收：对照本清单 + 移动端微信内浏览器实测。
