# 家长督促与定向分发 MVP 设计

## 背景与目标

家长需要轻参与，而不是接管学生所有学习细节。本 MVP 解决两个实际问题：

1. 家长打开学生详情后，能一眼知道最近该提醒什么。
2. 家长发试卷时能确认“发给谁”，学生只看到发给自己的任务。

本功能不做兴趣审批、不做复杂班级后台、不做强提醒轰炸。家长只看边界、督促和任务来源；学生继续保留每日回顾、兴趣和学习目标的主导权。

## 复用结论

实现前已检查现有能力：

- `access_service.teacher_can_access_student` / `list_accessible_students`：复用家长-学生权限边界。
- `learning_map_service.build_learning_map`：复用错题、笔记、素材、计划聚合，不重写“薄弱知识点”统计。
- `p2_service.list_due_study_plan_reminders`：复用未完成计划和逾期提醒。
- `note_service.list_notes` 与每日回顾 Markdown 格式：复用学生写的“需要督促的地方”。
- `exam_assignments`、`exam_service.assign_exam`、`ExamManagePage`：复用试卷定向分发，不新增任务系统。
- `notification_service`：后续可复用到分发提醒；本 MVP 不强制新增推送。

外部开源方案暂不接入：本 MVP 是现有业务数据聚合和权限展示，不需要引入第三方 dashboard、任务队列或报表系统。

## MVP 能力

### 1. 家长督促摘要 API

新增后端聚合能力：

`GET /api/students/{student_id}/supervision-summary`

仅绑定家长可访问；学生本人暂不需要访问此家长视角接口。

返回内容：

- 学生基本信息：`student_id`、`student_name`。
- 需要提醒：来自未完成/逾期学习计划，复用 `StudyPlanReminder`。
- 学生自己写的督促点：从最近每日回顾笔记中解析 `## 需要督促的地方` 小节。
- 高频薄弱点：从学习地图取 `weak` 节点前 5 个，带错题次数、最近错误时间和下一步建议。
- 最近定向分发：从 `exam_assignments` 取最近 5 条，展示试卷标题、状态、截止时间和备注。
- 周报草稿：只引用以上真实数据，生成可展示的 deterministic 草稿，不调用 LLM、不编造。

### 2. 家长页面入口

在学生详情页增加“督促面板”视图或 tab。

展示原则：

- 第一屏优先展示三类信息：今天/近期要提醒、反复错什么、学生自己说需要什么督促。
- 每条建议都要能看出来源，例如“来自每日回顾”“来自学习计划”“来自学习地图”。
- 周报草稿是“可参考草稿”，不自动保存为笔记，也不冒充 AI 最终结论。
- “分发试卷”入口跳现有 `/teacher/exams`，继续使用现有分发弹窗。

### 3. 定向分发保持现有模型

现有 `exam_assignments` 已满足“发给谁”和“学生只看自己的任务”：

- 家长分发：`POST /api/exam/{exam_id}/assignments`
- 学生可见：`exam_service.list_exams` 根据 assignment 过滤
- 学生打开试卷：`get_exam_detail` 校验 active assignment

本 MVP 只在督促面板展示最近分发状态，不新建通用任务表。

## 数据结构

新增 schema 文件 `app/schemas/supervision.py`：

- `SupervisionReminderItem`
- `SupervisionSupportItem`
- `SupervisionWeakPointItem`
- `SupervisionAssignmentItem`
- `WeeklyReportDraft`
- `SupervisionSummaryResponse`

字段保持展示友好，不把 ORM 模型直接暴露给前端。

## 后端设计

新增 `app/services/supervision_service.py`：

- `build_supervision_summary(db, student_id, now=None)`：聚合所有数据。
- `_extract_support_section(content)`：解析每日回顾中的 `## 需要督促的地方`。
- `_build_weekly_report_draft(...)`：根据真实数据生成草稿。

新增 `app/routers/supervision.py`：

- 校验当前用户是 teacher/parent。
- 校验 `teacher_can_access_student`。
- 返回 `SupervisionSummaryResponse`。

`app/main.py` 挂载 router。

## 前端设计

新增 `src/api/supervision.ts` 和类型。

学生详情页新增 tab：

- 标题：`督促面板`
- 顶部三块简洁指标：待提醒计划、薄弱点、最近分发
- 主内容：
  - 需要提醒
  - 学生自己写的需要督促
  - 高频薄弱点
  - 最近分发
  - 本周学习情况草稿

样式复用 `StudentDetailPage`、`AppPageShell`、AntD `Card/Tag/List/Button` 和现有 `--sb-*` token，不新增颜色体系。

## 权限与边界

- 未绑定家长访问返回 403。
- 学生不能访问家长督促摘要接口。
- 周报草稿只引用真实数据；没有数据时显示“暂时没有足够记录”，不编造。
- 督促点来自学生每日回顾，不允许家长在这里审批或覆盖兴趣。

## 测试计划

后端：

- service 聚合未完成计划、每日回顾督促点、weak 学习地图节点、最近分发。
- service 在无数据时返回空列表和“不足记录”的周报草稿。
- API：绑定家长可访问，未绑定家长 403，学生访问 403。

前端：

- 学生详情页能加载督促面板并展示真实字段。
- 无数据时显示空态。
- 点击“去分发试卷”跳转 `/teacher/exams`。

浏览器验收：

1. 登录家长账号。
2. 进入学生详情。
3. 打开“督促面板”。
4. 确认页面能看到提醒、薄弱点、学生自写督促点和最近分发。
5. 点击“去分发试卷”，确认进入现有试卷管理页。
6. 切学生账号，确认学生试卷页仍只显示分发给自己的试卷。

## 不做事项

- 不做微信推送。
- 不做自动保存周报。
- 不做家长审批兴趣。
- 不做新任务系统。
- 不引入图数据库或 mem0 作为本功能依赖。
