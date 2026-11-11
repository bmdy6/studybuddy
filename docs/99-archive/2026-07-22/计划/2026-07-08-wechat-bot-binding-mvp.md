# WeChat Bot Binding MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first WeChat Bot binding MVP: account page QR/bind-code UI, backend bind sessions, WeChat callback verification, text-code binding, and unbind.

**Architecture:** Add a small WeChat channel module that only handles identity binding. It stores temporary bind sessions and active openid bindings, reuses current JWT auth for web APIs, and keeps WeChat protocol handling isolated from learning business logic.

**Tech Stack:** FastAPI, SQLAlchemy, MySQL 5.7, React 18, AntD 5, Vitest, pytest.

## Global Constraints

- Do not add personal WeChat automation.
- Do not read WeChat chat history, friends, moments, payment, or asset data.
- Config must come from env via `app/config.py`.
- Use TDD: write failing tests before production code.
- First MVP may use a fake QR provider; real access_token/ticket/media provider comes later.

---

### Task 1: Backend Bind Session Service

**Files:**
- Create: `studybuddy-backend/app/models/wechat.py`
- Create: `studybuddy-backend/app/schemas/wechat.py`
- Create: `studybuddy-backend/app/services/wechat_service.py`
- Create: `studybuddy-backend/sql/017_wechat_bindings.sql`
- Modify: `studybuddy-backend/app/models/__init__.py`
- Modify: `studybuddy-backend/app/config.py`
- Test: `studybuddy-backend/tests/unit/test_wechat_service.py`

**Interfaces:**
- Produces: `create_bind_session(db: Session, user: User) -> WechatBindSession`
- Produces: `get_active_account(db: Session, user_id: int) -> WechatAccount | None`
- Produces: `unbind_account(db: Session, user: User) -> None`
- Produces: `complete_bind_by_code(db: Session, bind_code: str, openid: str) -> WechatBindSession`

- [ ] Write tests for session creation, expiry, one-time bind, same-openid replacement prevention, and unbind.
- [ ] Run `cd studybuddy-backend && PYTHONPATH=. pytest tests/unit/test_wechat_service.py -q` and confirm expected failures.
- [ ] Implement models, schemas, service, config, and SQL migration.
- [ ] Run the same tests and confirm pass.

### Task 2: Backend Router And WeChat Callback

**Files:**
- Create: `studybuddy-backend/app/routers/wechat.py`
- Modify: `studybuddy-backend/app/main.py`
- Test: `studybuddy-backend/tests/api/test_wechat.py`

**Interfaces:**
- Consumes Task 1 service functions.
- Produces:
  - `POST /api/channels/wechat/bind-sessions`
  - `GET /api/channels/wechat/bind-sessions/{session_id}`
  - `GET /api/channels/wechat/account`
  - `DELETE /api/channels/wechat/account`
  - `GET /api/channels/wechat/callback`
  - `POST /api/channels/wechat/callback`

- [ ] Write API tests for auth-required session creation, polling, unbind, GET callback signature, POST text bind-code callback.
- [ ] Run `cd studybuddy-backend && PYTHONPATH=. pytest tests/api/test_wechat.py -q` and confirm expected failures.
- [ ] Implement router and XML passive text reply helper.
- [ ] Run API tests and confirm pass.

### Task 3: Frontend Account Binding UI

**Files:**
- Create: `studybuddy-client/src/api/wechat.ts`
- Modify: `studybuddy-client/src/pages/AccountPage.tsx`
- Test: `studybuddy-client/src/test/AccountPage.test.tsx`

**Interfaces:**
- Consumes backend web APIs from Task 2.
- Produces account page card with security copy, QRCode, bind code, countdown, refresh, and unbind.

- [ ] Write UI tests for creating bind session and showing code/QR, bound state, and unbind action.
- [ ] Run `cd studybuddy-client && npm test -- AccountPage.test.tsx --run` and confirm expected failures.
- [ ] Implement API wrapper and account page card.
- [ ] Run UI tests and confirm pass.

### Task 4: Help, Docs, Verification

**Files:**
- Modify: `studybuddy-client/src/data/releaseNotes.ts`
- Modify: `docs/开发进度文档.md`
- Modify: `docs/已实现能力清单.md`
- Modify: `docs/人工验收清单.md`

- [ ] Add help/update note for WeChat binding MVP.
- [ ] Run backend focused tests.
- [ ] Run frontend lint/test/typecheck/build.
- [ ] Use Codex browser to verify account page binding card locally.
- [ ] Commit with a clear Chinese message.
