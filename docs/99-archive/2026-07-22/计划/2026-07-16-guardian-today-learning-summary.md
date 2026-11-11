# Guardian Today Learning Summary Implementation Plan

> **For agentic workers:** Choose superpowers:subagent-driven-development for multiple independent tasks with the required Git authorization; otherwise use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让家长微信 Bot 用最短文本准确回答孩子今天学了什么、真实记录了多久。

**Architecture:** 在现有家长身份和学生选择完成后，对今日学习查询走确定性摘要；复用成长证据收集和现有反馈/计划数据，其他问题继续进入只读 Agent。

**Tech Stack:** FastAPI service layer, SQLAlchemy, pytest, MiMo live test

## Global Constraints

- 不新增计时表或平行学习数据查询机制。
- 计划预计分钟数不能算作真实学习时长。
- 不实现平台停留时长和切出应用检测。
- 不改变现有家长与学生权限边界。

---

### Task 1: 家长今日摘要

**Files:**
- Modify: `studybuddy-backend/app/services/wechat_service.py`
- Modify: `studybuddy-backend/app/services/growth_summary_service.py`
- Test: `studybuddy-backend/tests/unit/test_wechat_service.py`
- Test: `studybuddy-backend/tests/live/test_wechat_guardian_agent_live.py`

**Interfaces:**
- Produces: `build_guardian_today_learning_summary(db: Session, student_id: int, now: datetime | None = None) -> str`
- Consumes: `collect_growth_evidence(..., period="daily", now=...)` and existing learning feedback/study-plan services.

- [x] **Step 1: Write failing tests**

Cover exact duration feedback, completed content, no-duration wording, empty-day wording, and the original “我小孩学习了多久啊？” message bypassing verbose Agent output.

- [x] **Step 2: Run tests to verify RED**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/unit/test_wechat_service.py -q`

Expected: FAIL because the deterministic summary and routing do not exist.

- [x] **Step 3: Implement the minimal service and routing**

Reuse existing daily evidence, read duration feedback within the same timezone bounds, include incomplete items only as pending work, and return short deterministic text.

- [x] **Step 4: Run focused and full backend tests**

Run focused unit tests, backend full pytest, and project lint checks.

- [ ] **Step 5: Run live guardian verification**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/live/test_wechat_guardian_agent_live.py --run-live -q`

Verify the original duration question returns a concise evidence-based answer without exposing private chat or using write tools.

Attempted on 2026-07-16: the existing multi-turn guardian live did not finish within 290 seconds and was interrupted. A direct short MiMo stream completed in 0.85 seconds, while the long-context live repeated the delay. The deterministic today-summary path itself does not call MiMo; real WeChat verification remains pending deployment.

- [ ] **Step 6: Review, commit, push and open PR**

Review the diff against project standards, commit with a concise Chinese message, push `feat/guardian-today-summary`, and create a PR to `main` without merging.
