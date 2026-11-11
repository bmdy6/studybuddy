# 计划草案状态机 Implementation Plan

> **For agentic workers:** Choose superpowers:subagent-driven-development for multiple independent tasks with the required Git authorization; otherwise use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把学习计划"草案->确认->创建"从靠聊天关键词猜，改成服务端草案对象 + Web 端点卡片按钮确认，消除反复复发的计划确认 bug。

**Architecture:** 新建 `study_plan_draft` 表存草案对象（draft_id/revision/status/expires_at/created_plan_id）；后端新增 `draft_study_plan` 工具存草案 + 原子"确认并创建"接口（用 draft_data 创建，行锁幂等）；前端抽 `ConfirmCard` 通用外壳 + `PlanDraftPanel` 展示草案并调确认接口；Web 路径 fail-closed 必须带 draft_id，微信旧路径临时兼容。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL 5.7（后端）；React + AntD + Zustand（前端）；裸 SQL 编号迁移（无 Alembic）。

**Spec:** `docs/11-功能/[未开始]主会话-计划草案状态机.md`

## Global Constraints

- 表名 `study_plan_draft`（单数，MySQL 5.7 小写不复数，必备 id/created_at/updated_at）
- Python snake_case / PascalCase；TS camelCase / PascalCase
- 迁移用 `sql/025_study_plan_draft.sql` + `scripts/run_ddl.py`，部署脚本 `deploy_backend.sh` 同步接入
- 不引入新前端 UI 库（用 AntD + `--sb-*` design token）
- Web 新路径 fail-closed（无 draft_id 拒绝），微信旧路径保留并记使用量
- 确认和创建是原子事务（抽只 flush 不 commit 的内部函数）；重复确认返回同 plan_id（行锁 + created_plan_id）；失败草案保持 pending 可重试
- 手动计划抽屉（ManualStudyPlanDrawer）不受影响，走现有直接创建 API
- 工作目录：`.worktrees/feat-agent-plan-state-machine`（已建）

---

## File Structure

**后端新建：**
- `sql/025_study_plan_draft.sql` - 草案表 DDL
- `app/models/study_plan_draft.py` - StudyPlanDraft ORM
- `app/features/agent/study_plan_flow.py` - 草案 service（存/查/确认并创建）

**后端修改：**
- `app/models/__init__.py` - 注册 StudyPlanDraft
- `app/features/p2/study_plan.py` - 抽出 `_create_plan_records`（只 flush 不 commit）
- `app/features/p2/schemas.py` - 加 StudyPlanDraftSchema / ConfirmResult
- `app/features/p2/router.py` - 加 `POST /api/study-plan-drafts/{id}/confirm`
- `app/features/agent/tools.py` - 加 `draft_study_plan` 工具定义
- `app/features/agent/handlers/learning.py` - 加 `_handle_draft_study_plan`
- `app/features/agent/handlers/__init__.py` - 注册 handler
- `app/features/agent/agent_loop.py` - Web 路径 create_study_plan fail-closed（需 draft_id）
- `scripts/deploy_backend.sh` - 接入 025 迁移

**前端新建：**
- `src/shared/components/ConfirmCard.tsx` - 通用确认卡片外壳
- `src/features/chat/components/PlanDraftPanel.tsx` - 计划草案确认卡

**前端修改：**
- `src/features/chat/store.ts` - 解析 draft_study_plan tool_result + pendingPlanDraft 状态 + 刷新恢复；create_study_plan 只在 created 时刷新
- `src/features/chat/components/ChatComposer.tsx` - 挂载 PlanDraftPanel
- `src/features/p2/api.ts` - 加 confirmPlanDraft 接口
- `src/types/index.ts` - 加 PlanDraftState 类型
- `src/features/chat/components/NoteDraftPanel.tsx` / `PhotoAnswerReviewPanel.tsx` - 改用 ConfirmCard（可选，低优先）

---

### Task 1: 草案表 + ORM + 迁移

**Files:**
- Create: `sql/025_study_plan_draft.sql`
- Create: `app/models/study_plan_draft.py`
- Modify: `app/models/__init__.py`
- Test: `tests/unit/test_study_plan_draft_model.py`

**Interfaces:**
- Produces: `StudyPlanDraft` ORM（id/student_id/created_by/chat_session_id/draft_data/revision/status/expires_at/created_plan_id/created_at/updated_at）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_study_plan_draft_model.py
from app.models.study_plan_draft import StudyPlanDraft

def test_study_plan_draft_fields():
    d = StudyPlanDraft(
        student_id=1, chat_session_id=10, draft_data={"title": "t"},
        revision=1, status="pending",
    )
    assert d.status == "pending"
    assert d.created_plan_id is None
```

- [ ] **Step 2: 跑测试验证失败**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/unit/test_study_plan_draft_model.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 ORM model**

```python
# app/models/study_plan_draft.py
from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Integer, JSON, String, func
from app.database import Base


class StudyPlanDraft(Base):
    __tablename__ = "study_plan_draft"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    student_id = Column(BigInteger, nullable=False, index=True)
    created_by = Column(BigInteger, nullable=True)
    chat_session_id = Column(BigInteger, nullable=True, index=True)
    draft_data = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="pending")  # pending/created/superseded
    expires_at = Column(DateTime, nullable=True)
    created_plan_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: 注册到 `app/models/__init__.py`**

加 `from .study_plan_draft import StudyPlanDraft`。

- [ ] **Step 5: 写迁移 SQL**

```sql
-- sql/025_study_plan_draft.sql
CREATE TABLE IF NOT EXISTS study_plan_draft (
  id BIGINT NOT NULL AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  created_by BIGINT NULL,
  chat_session_id BIGINT NULL,
  draft_data JSON NOT NULL,
  revision INT NOT NULL DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  expires_at DATETIME NULL,
  created_plan_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_draft_student (student_id),
  KEY idx_draft_session (chat_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 6: 跑迁移 + 测试**

Run: `cd studybuddy-backend && PYTHONPATH=. .venv/bin/python scripts/run_ddl.py sql/025_study_plan_draft.sql && .venv/bin/python -m pytest tests/unit/test_study_plan_draft_model.py -v`
Expected: PASS

---

### Task 2: 草案 service + 抽内部建记录函数

**Files:**
- Create: `app/features/agent/study_plan_flow.py`
- Modify: `app/features/p2/study_plan.py`（抽 `_create_plan_records`）
- Modify: `app/features/p2/schemas.py`（加 StudyPlanDraftSchema / ConfirmResult）
- Test: `tests/unit/test_study_plan_flow.py`

**Interfaces:**
- Consumes: `p2/study_plan._create_plan_records(db, student_id, title, items, ...)` -> flush 不 commit
- Produces: `create_draft(db, student_id, chat_session_id, draft_data, created_by) -> StudyPlanDraft`；`get_draft(db, draft_id, student_id) -> StudyPlanDraft | None`；`confirm_and_create(db, draft_id, revision, student_id, created_by) -> ConfirmResult`

- [ ] **Step 1: 写失败测试（核心：幂等 + 原子 + 用 draft_data）**

```python
# tests/unit/test_study_plan_flow.py
from app.features.agent import study_plan_flow as flow

def test_confirm_returns_same_plan_id_on_duplicate(db_session, draft_factory):
    d = draft_factory(status="pending", revision=1)
    r1 = flow.confirm_and_create(db_session, d.id, 1, d.student_id, None)
    r2 = flow.confirm_and_create(db_session, d.id, 1, d.student_id, None)
    assert r1.plan_id == r2.plan_id
    assert r1.plan_id is not None

def test_old_revision_rejected(db_session, draft_factory):
    d = draft_factory(status="pending", revision=1)
    r = flow.confirm_and_create(db_session, d.id, 2, d.student_id, None)
    assert r.plan_id is None
    assert "revision" in r.error

def test_uses_draft_data_not_args(db_session, draft_factory):
    d = draft_factory(draft_data={"title": "草案标题", "items": [...]}, revision=1)
    r = flow.confirm_and_create(db_session, d.id, 1, d.student_id, None)
    # 即使调用方想传别的，也用 draft_data
    plan = get_plan(r.plan_id)
    assert plan.title == "草案标题"

def test_cross_student_rejected(db_session, draft_factory):
    d = draft_factory(student_id=1)
    r = flow.confirm_and_create(db_session, d.id, 1, 2, None)
    assert r.plan_id is None
    assert "权限" in r.error or "归属" in r.error
```

- [ ] **Step 2: 跑测试验证失败**

- [ ] **Step 3: 抽 `p2/study_plan.py` 内部 flush 函数**

把现有 `create_study_plan` 的落库部分抽成 `_create_plan_records(db, student_id, title, items, ...) -> StudyPlan`，只 `flush`（拿 id），不 `commit`。原 `create_study_plan` 调它后 `commit`，保持现有 API 不变。

- [ ] **Step 4: 写 study_plan_flow.py**

```python
# app/features/agent/study_plan_flow.py
from datetime import datetime, timedelta
from sqlalchemy.orm import with_for_update
from app.models import StudyPlan, StudyPlanDraft
from app.features.p2 import study_plan as plan_service

DRAFT_TTL_MINUTES = 30

def create_draft(db, student_id, chat_session_id, draft_data, created_by):
    # 旧 pending 草案标 superseded
    db.query(StudyPlanDraft).filter(
        StudyPlanDraft.student_id == student_id,
        StudyPlanDraft.status == "pending",
    ).update({"status": "superseded"})
    draft = StudyPlanDraft(
        student_id=student_id, created_by=created_by,
        chat_session_id=chat_session_id, draft_data=draft_data,
        revision=1, status="pending",
        expires_at=datetime.now() + timedelta(minutes=DRAFT_TTL_MINUTES),
    )
    db.add(draft); db.flush()
    return draft

def get_draft(db, draft_id, student_id):
    return db.query(StudyPlanDraft).filter(
        StudyPlanDraft.id == draft_id, StudyPlanDraft.student_id == student_id,
    ).first()

def confirm_and_create(db, draft_id, revision, student_id, created_by):
    # 行锁
    draft = db.query(StudyPlanDraft).filter(
        StudyPlanDraft.id == draft_id, StudyPlanDraft.student_id == student_id,
    ).with_for_update().first()
    if not draft:
        return ConfirmResult(None, "草案不存在或无权访问")
    if draft.student_id != student_id:
        return ConfirmResult(None, "无权确认此草案")
    if draft.created_plan_id:  # 幂等
        return ConfirmResult(draft.created_plan_id, None)
    if draft.revision != revision:
        return ConfirmResult(None, f"草案已修改，请确认最新版本(revision={draft.revision})")
    if draft.status == "superseded":
        return ConfirmResult(None, "已有更新的草案")
    if draft.expires_at and datetime.now() > draft.expires_at:
        return ConfirmResult(None, "草案已过期，请重新生成")
    # 用 draft_data 创建（不接受外部传参）
    data = draft.draft_data
    plan = plan_service._create_plan_records(
        db, student_id, data["title"], data["items"],
        focus=data.get("focus"), planned_date=data.get("planned_date"),
        created_by=created_by,
    )
    draft.status = "created"
    draft.created_plan_id = plan.id
    db.commit()  # 原子：计划 + 草案状态一起提交
    return ConfirmResult(plan.id, None)
```

- [ ] **Step 5: 加 schemas**

```python
# app/features/p2/schemas.py
class StudyPlanDraftSchema(BaseModel):
    id: int; student_id: int; draft_data: dict; revision: int
    status: str; expires_at: datetime | None; created_plan_id: int | None

class ConfirmResult(BaseModel):
    plan_id: int | None
    error: str | None
    @property
    def ok(self): return self.plan_id is not None
```

- [ ] **Step 6: 跑测试验证通过**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/unit/test_study_plan_flow.py -v`
Expected: PASS

---

### Task 3: draft_study_plan 工具 + handler

**Files:**
- Modify: `app/features/agent/tools.py`（加工具定义）
- Modify: `app/features/agent/handlers/learning.py`（加 `_handle_draft_study_plan`）
- Modify: `app/features/agent/handlers/__init__.py`
- Test: `tests/unit/test_agent_loop.py`（加用例）

**Interfaces:**
- Produces: `draft_study_plan` 工具（参数 student_id/title/items/focus/planned_date），返回 `{draft_id, revision, expires_at}`

- [ ] **Step 1: 写失败测试（AI 调 draft_study_plan 存草案返回 draft_id）**

- [ ] **Step 2: 加工具定义到 tools.py**

```python
_TOOL_DRAFT_STUDY_PLAN = {
    "name": "draft_study_plan",
    "description": "给学生展示学习计划草案，等学生在卡片上点'确认并创建'后才正式建计划。不要让学生用文字'可以'确认。",
    "parameters": {
        "type": "object",
        "required": ["student_id", "title", "items"],
        "properties": {
            "student_id": {"type": "integer"},
            "title": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", ...}},
            "focus": {"type": "string"},
            "planned_date": {"type": "string"},
        },
    },
}
```
加到 `STUDENT_TOOLS`。`create_study_plan` 从 STUDENT_TOOLS 移除（Web 不再直接暴露）。

- [ ] **Step 3: 加 handler**

```python
async def _handle_draft_study_plan(args, role, db, teacher_id):
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    data = {"title": args["title"], "items": args["items"],
            "focus": args.get("focus"), "planned_date": args.get("planned_date")}
    draft = study_plan_flow.create_draft(db, sid, args.get("chat_session_id"), data, teacher_id)
    return {"draft_id": draft.id, "revision": draft.revision,
            "expires_at": draft.expires_at.isoformat() if draft.expires_at else None}
```

- [ ] **Step 4: 跑测试验证通过**

---

### Task 4: "确认并创建" HTTP 接口

**Files:**
- Modify: `app/features/p2/router.py`
- Modify: `app/features/p2/schemas.py`（加 ConfirmRequest）
- Test: `tests/api/test_p2.py`

**Interfaces:**
- Produces: `POST /api/study-plan-drafts/{draft_id}/confirm` body `{revision}` -> `{plan_id}` 或 `{error}`

- [ ] **Step 1: 写失败测试**

```python
def test_confirm_creates_plan(client, auth_student, draft_factory):
    d = draft_factory(student_id=auth_student.id)
    r = client.post(f"/api/study-plan-drafts/{d.id}/confirm",
                    headers=auth_student.headers, json={"revision": 1})
    assert r.status_code == 200
    assert r.json()["plan_id"] is not None

def test_confirm_cross_student_rejected(client, auth_student, draft_factory):
    d = draft_factory(student_id=999)
    r = client.post(f"/api/study-plan-drafts/{d.id}/confirm",
                    headers=auth_student.headers, json={"revision": 1})
    assert r.json()["plan_id"] is None
```

- [ ] **Step 2: 实现路由**

```python
@router.post("/study-plan-drafts/{draft_id}/confirm")
async def confirm_plan_draft(draft_id: int, body: ConfirmRequest,
                             student_id: int = Depends(require_student), db = Depends(get_db)):
    r = study_plan_flow.confirm_and_create(db, draft_id, body.revision, student_id, None)
    if not r.ok:
        raise HTTPException(400, r.error)
    return {"plan_id": r.plan_id}
```

- [ ] **Step 3: 跑测试验证通过**

---

### Task 5: 前端 ConfirmCard 通用外壳

**Files:**
- Create: `src/shared/components/ConfirmCard.tsx`
- Test: `src/shared/components/__tests__/ConfirmCard.test.tsx`

**Interfaces:**
- Produces: `<ConfirmCard title hint tag confirmLabel onConfirm confirming>` 包外壳，children 是内容区

- [ ] **Step 1: 写失败测试（渲染标题/按钮/点确认回调）**

- [ ] **Step 2: 实现 ConfirmCard**

抽 NoteDraftPanel/PhotoAnswerReviewPanel 的重复外壳（白底+边框+圆角+阴影+标题+Tag+底部按钮）为 `ConfirmCard`，`children` 放内容。

- [ ] **Step 3: 跑测试验证通过**

Run: `cd studybuddy-client && npm test -- ConfirmCard`

---

### Task 6: PlanDraftPanel + store 改造

**Files:**
- Create: `src/features/chat/components/PlanDraftPanel.tsx`
- Modify: `src/features/chat/store.ts`（解析 draft_study_plan + pendingPlanDraft + 刷新恢复）
- Modify: `src/features/chat/components/ChatComposer.tsx`
- Modify: `src/features/p2/api.ts`（confirmPlanDraft）
- Modify: `src/types/index.ts`（PlanDraftState）
- Test: `src/features/chat/__tests__/PlanDraftPanel.test.tsx`

**Interfaces:**
- Consumes: `POST /api/study-plan-drafts/{id}/confirm`
- Produces: `pendingPlanDraft` store 状态；`extractPlanDraftFromToolOutput`

- [ ] **Step 1: 写失败测试**

```tsx
// 点击确认调 confirmPlanDraft + 发确认消息
// store 收到 draft_study_plan tool_result 后存 pendingPlanDraft
// 刷新后从历史 + API 恢复 pendingPlanDraft
```

- [ ] **Step 2: 加类型 + API**

```ts
// types
interface PlanDraftState { draftId: number; revision: number; title: string; items: PlanItem[]; expiresAt?: string }
// api
export const confirmPlanDraft = (draftId: number, revision: number) =>
  postJSON(`/api/study-plan-drafts/${draftId}/confirm`, { revision })
```

- [ ] **Step 3: store.ts 解析 + 状态 + 刷新恢复**

仿 `pendingNoteDraft`：`tool_result` 分支对 `draft_study_plan` 解析草案存 `pendingPlanDraft`；`switchSession` 从历史恢复；`create_study_plan` 的 `planVersion++` 改为只在 `saved:true` 时。

- [ ] **Step 4: PlanDraftPanel 基于 ConfirmCard**

展示草案标题/任务列表/时间，"确认并创建"按钮调 `confirmPlanDraft` + 发确认消息。

- [ ] **Step 5: ChatComposer 挂载**

- [ ] **Step 6: 跑测试验证通过**

---

### Task 7: Web fail-closed + 微信兼容

**Files:**
- Modify: `app/features/agent/agent_loop.py`（Web create_study_plan 需 draft_id）
- Modify: `app/features/agent/study_plan_confirmation.py`（记微信使用量）
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: 写失败测试（Web 无 draft_id 调 create_study_plan 被拒）**

- [ ] **Step 2: agent_loop 拦截**

Web 路径（非微信）调 `create_study_plan` 时，若 args 无 `draft_id` -> 返回 blocked（"请先用 draft_study_plan 生成草案"）。微信路径（business_actor=channel_guardian 或 session 来源微信）保留旧 `validate_study_plan_confirmation` 兜底，并 log 使用量。

- [ ] **Step 3: 跑测试 + 现有计划 guard 测试不回归**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/unit/test_agent_loop.py tests/unit/test_study_plan_confirmation_service.py -v`

---

### Task 8: 部署迁移接入 + 验收

**Files:**
- Modify: `scripts/deploy_backend.sh`（接入 025 迁移执行）
- Test: 手动 + live

- [ ] **Step 1: deploy_backend.sh 接入 025 迁移**

在部署后执行 `run_ddl.py sql/025_study_plan_draft.sql`（幂等，CREATE TABLE IF NOT EXISTS）。

- [ ] **Step 2: 后端全量测试**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest -q`

- [ ] **Step 3: 前端测试 + lint + build**

Run: `cd studybuddy-client && npm run lint && npm test && npm run typecheck && npm run build`

- [ ] **Step 4: 部署 + 公网手机端验收（按验收矩阵 11 条）**

- [ ] **Step 5: 真实 MiMo live 测试**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/live/ --run-live -k plan`

---

## Self-Review

- **Spec coverage**: 草案表✓ draft_study_plan✓ 确认并创建✓ 原子事务✓ 幂等✓ 失败可重试(pending 保持)✓ Web fail-closed✓ 微信兼容✓ 手动抽屉不动✓ ConfirmCard✓ PlanDraftPanel✓ 刷新恢复✓ 迁移接入部署✓ 验收矩阵覆盖在 Task 8。
- **Placeholder**: test 工厂函数(draft_factory/auth_student)需在 conftest 补，已在测试中标注。
- **Type consistency**: `confirm_and_create` 返回 `ConfirmResult`，router 返回 `{plan_id}`，前端 `confirmPlanDraft` 返回 `{plan_id}`，一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-01-plan-draft-state-machine.md`。建议 Inline Execution（任务间有依赖，单 session 批量执行 + checkpoint）。
