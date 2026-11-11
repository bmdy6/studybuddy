# README 功能与源码入口

| 功能 | 客户端 | 后端 / 服务 |
| --- | --- | --- |
| 计划草案确认 | `src/features/chat/store.ts`、计划确认卡片 | `app/features/agent/study_plan_confirmation.py`、`app/features/p2/study_plan.py` |
| 任务会话、作答证据、继续 | `src/features/chat/`、`src/features/learning/pages/StudyPlansPage.tsx` | `app/features/chat/`、`app/features/p2/`、`StudyPlanItemAttempt` |
| 未完成项目沿用 | `src/features/chat/store.ts`、计划页 | `app/features/agent/study_plan_flow.py`、`app/features/p2/study_plan.py` |
| 微信连接、家长绑定 | `src/features/wechat/`、个人中心 | `app/features/wechat/`、`wechat_bot_service/` |
| 定时日报、成长汇报 | 微信绑定页及推送时间设置 | `app/features/wechat/dispatch.py`、`app/features/growth/dispatch.py`；`scripts/refresh_daily_learning_records.py`、`scripts/dispatch_wechat_parent_reminders.py`（后端目录） |
| 笔记 | `src/features/note/` | `app/features/note/` |
| PDF / 照片解析 | `src/features/materials/` | `app/features/materials/` |
| 试卷、错题、轻练 | `src/features/exams/`、`src/features/error_book/`、聊天页 | `app/features/exams/`、`app/features/error_book/`、`app/features/agent/handlers/exam.py` |
| 家庭任务 | `src/features/family_goal/` | `app/features/family_goal/` |
| 每日学习事实与成长记录 | `src/features/growth/` | `app/features/growth/` |
| 官网 | `src/landing/`、`landing.html` | `vite.landing.config.ts`（独立静态产物） |
| 趣爱好 | `hobbybuddy/client/` | `hobbybuddy/backend/`，独立数据库，复用底座模型和资源搜索 |

客户端路径相对 `studybuddy-client`，后端路径相对 `studybuddy-backend`。计划沿用需要用户确认，不承诺无人确认的自动建计划；日报需配置定时任务，发送受平台窗口与配额限制。历史设计文档包含未实施方案，不能单凭文档名判断功能已实现。
