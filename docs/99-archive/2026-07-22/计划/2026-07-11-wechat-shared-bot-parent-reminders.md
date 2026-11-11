# WeChat Shared Bot Parent And Reminder Implementation Plan

> **For agentic workers:** Choose superpowers:subagent-driven-development for multiple independent tasks with the required Git authorization; otherwise use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the shared iLink Bot MVP with existing-parent invitations, parent commands, and quota-aware scheduled reminders.

**Architecture:** Reuse `WechatBindSession` as the three-minute parent invitation instead of adding a new invitation table. The backend remains the only owner of parent-student authorization, summaries, reminder policy, and counters; the Bot microservice only sends text to the shared Bot plus one `ilink_user_id`. Extend the existing reminder dispatcher rather than creating a second scheduler.

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, httpx, React, TypeScript, Ant Design, qrcode.react, Vitest, pytest

## Global Constraints

- Run one shared iLink Bot and one `WeixinAdapter`; isolate users by `provider_account_id + ilink_user_id`.
- Use only existing `teacher_students` relationships; never create users or relationships from WeChat.
- Reuse `supervision_service.build_supervision_summary()` for `今日学情`; do not call an LLM.
- Keep addresses, secrets, timeouts, time zone, interaction window, and proactive quota in required environment variables with no code defaults.
- Keep all UI copy neutral: use `微信学习助手`, `绑定微信`, and `进入工具`; do not add a brand-management surface.
- Do not commit, push, deploy, or change company infrastructure without separate authorization.

---

### Task 1: Parent Invitation And iLink Commands

**Files:**
- Modify: `studybuddy-backend/app/schemas/wechat.py`
- Modify: `studybuddy-backend/app/models/wechat.py`
- Modify: `studybuddy-backend/app/services/wechat_service.py`
- Modify: `studybuddy-backend/app/routers/wechat.py`
- Modify: `studybuddy-backend/scripts/ensure_wechat_tables.py`
- Test: `studybuddy-backend/tests/api/test_wechat.py`
- Test: `studybuddy-backend/tests/unit/test_wechat_service.py`

**Interfaces:**
- Consumes: `access_service.list_bound_teachers(db, student_id)`, `create_bind_session(..., channel=WECHAT_CHANNEL_ILINK_BOT)`, and `handle_parent_command(db, account, content)`.
- Produces: nullable `WechatBindSession.invited_by_user_id`, `create_parent_invitation_reply(db, student) -> str`, and `GET /api/channels/wechat/parent-invitations/{scene}` returning `WechatParentInvitationResponse`.

- [ ] **Step 1: Write failing API tests for invitation authorization and iLink parent commands**

```python
def test_bound_ilink_student_can_invite_only_existing_parent(...):
    response = post_ilink_message(student_identity, "邀请家长")
    assert response.json()["reply"].startswith("测试家长：")
    scene = parse_invitation_scene(response.json()["reply"])
    invitation = client.get(f"/api/channels/wechat/parent-invitations/{scene}")
    assert invitation.json()["parent_name"] == "测试家长"
    assert invitation.json()["student_name"] == "测试学生"

def test_bound_ilink_parent_can_query_and_configure_reminders(...):
    assert "测试学生今日学情" in post_ilink_message(parent_identity, "今日学情").json()["reply"]
    assert post_ilink_message(parent_identity, "提醒 09:00 20:30").json()["reply"] == "提醒时间已设置：09:00、20:30"
```

- [ ] **Step 2: Run the focused tests and confirm missing route/command failures**

Run: `cd studybuddy-backend && pytest -q tests/api/test_wechat.py -k 'invite or ilink_parent'`

Expected: FAIL because the invitation route and iLink command routing do not exist.

- [ ] **Step 3: Implement invitations by reusing bind sessions**

```python
def create_parent_invitation_reply(db: Session, student: User) -> str:
    parents = access_service.list_bound_teachers(db, student.id)
    if not parents:
        return "当前没有已绑定家长"
    lines = []
    for parent in parents:
        session = create_bind_session(
            db,
            parent,
            channel=WECHAT_CHANNEL_ILINK_BOT,
            invited_by_user_id=student.id,
        )
        url = f"{settings.WECHAT_PARENT_INVITATION_URL}?{urlencode({'token': session.scene})}"
        lines.append(f"{parent.display_name or parent.username}：{url}")
    return "\n".join(lines)
```

Add nullable `invited_by_user_id` to the existing bind-session model and compatibility migration. The public route loads by unguessable `scene`, rejects missing/non-invitation sessions, rechecks the exact `teacher_students` relationship, refreshes provider QR status, and returns only parent name, student name, QR value, binding code, status, and expiry. An expired invitation returns `status="expired"` so the page can render its terminal state.

When consuming a parent invitation code, recheck `access_service.teacher_can_access_student(db, parent.id, session.invited_by_user_id)` so a removed relationship cannot be used after the link was generated.

- [ ] **Step 4: Route `邀请家长` and existing parent commands in the iLink handler**

```python
if account:
    user = db.get(User, account.user_id)
    if content == "邀请家长" and user and user.role == "student":
        return WechatIlinkMessageResponse(reply=wechat_service.create_parent_invitation_reply(db, user))
    parent_reply = wechat_service.handle_parent_command(db, account, content)
    if parent_reply is not None:
        return WechatIlinkMessageResponse(reply=parent_reply)
```

- [ ] **Step 5: Run focused backend tests and inspect the diff**

Run: `cd studybuddy-backend && pytest -q tests/api/test_wechat.py tests/unit/test_wechat_service.py`

Expected: all WeChat API and service tests PASS.

### Task 2: Public Parent Binding Page

**Files:**
- Create: `studybuddy-client/src/pages/WechatParentBindPage.tsx`
- Modify: `studybuddy-client/src/App.tsx`
- Modify: `studybuddy-client/src/api/wechat.ts`
- Modify: `studybuddy-client/src/index.css`
- Create: `studybuddy-client/src/test/WechatParentBindPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/channels/wechat/parent-invitations/{scene}` from Task 1.
- Produces: public hash route `#/wechat-parent-bind?token=<scene>`.

- [ ] **Step 1: Write failing page tests for loading, pending, bound, and expired states**

```tsx
it('shows the parent and student names with the QR and bind code', async () => {
  mockGetParentInvitation.mockResolvedValue({
    parent_name: '测试家长', student_name: '测试学生', bind_code: 'WABC123',
    qr_value: 'https://example.test/qr', status: 'pending', expires_at: future,
  });
  renderPage('/wechat-parent-bind?token=scene-token');
  expect(await screen.findByText('测试家长')).toBeInTheDocument();
  expect(screen.getByText('WABC123')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the page test and confirm the route/component is missing**

Run: `cd studybuddy-client && npm test -- --run src/test/WechatParentBindPage.test.tsx`

Expected: FAIL because the page and API method do not exist.

- [ ] **Step 3: Implement the public single-column page**

Use `QRCodeSVG` for `qr_value`, poll every three seconds while pending, show a one-second countdown based on `expires_at`, and stop polling on `bound` or `expired`. The page contains only the relationship names, QR, bind code, countdown, and current status; it uses `min-height: 100dvh` and existing warm background/teal tokens.

- [ ] **Step 4: Register the public route and API method**

```tsx
const WechatParentBindPage = lazy(() => import('./pages/WechatParentBindPage'));
<Route path="/wechat-parent-bind" element={<WechatParentBindPage />} />
```

```ts
getParentInvitation: (scene: string) =>
  client.get<WechatParentInvitation>(`/api/channels/wechat/parent-invitations/${encodeURIComponent(scene)}`).then((r) => r.data),
```

- [ ] **Step 5: Run page tests, lint, and typecheck**

Run: `cd studybuddy-client && npm test -- --run src/test/WechatParentBindPage.test.tsx && npm run lint && npm run typecheck`

Expected: all commands PASS.

### Task 3: iLink Reminder Quota And Provider Results

**Files:**
- Modify: `studybuddy-backend/app/config.py`
- Modify: `studybuddy-backend/.env.example`
- Modify: `studybuddy-backend/app/models/wechat.py`
- Modify: `studybuddy-backend/scripts/ensure_wechat_tables.py`
- Modify: `studybuddy-backend/app/services/wechat_service.py`
- Test: `studybuddy-backend/tests/unit/test_wechat_service.py`
- Test: `studybuddy-backend/tests/unit/test_ensure_wechat_tables_script.py`

**Interfaces:**
- Consumes: Bot `POST /v1/messages` returning `success`, `window_closed`, `session_expired`, `not_allowed`, or `failed`.
- Produces: required `WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT`, persisted `proactive_message_count`, and `proactive_message_window_started_at`.

- [ ] **Step 1: Write failing tests for success-only counters, quota, interaction reset, window, idempotency, and provider failure**

```python
def test_ilink_reminder_increments_only_after_success(...):
    result = dispatch_parent_reminders(db, now=due, send_ilink=lambda *_: "success")
    assert result["sent"] == 1
    assert account.proactive_message_count == 1

def test_ilink_reminder_pauses_at_quota(...):
    account.proactive_message_count = settings.WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT
    assert dispatch_parent_reminders(db, now=due, send_ilink=fail_if_called)["paused"] == 1

def test_inbound_interaction_resets_ilink_quota(...):
    record_interaction(db, account.openid, channel=WECHAT_CHANNEL_ILINK_BOT, provider_account_id=account.provider_account_id)
    assert account.proactive_message_count == 0
```

- [ ] **Step 2: Run focused tests and confirm missing fields/config failures**

Run: `cd studybuddy-backend && pytest -q tests/unit/test_wechat_service.py tests/unit/test_ensure_wechat_tables_script.py`

Expected: FAIL because quota fields and iLink sending do not exist.

- [ ] **Step 3: Add required configuration and compatible columns**

```python
WECHAT_BOT_PROACTIVE_MESSAGE_LIMIT: int = Field(gt=0)
```

Add `proactive_message_count INT NOT NULL DEFAULT 0` and `proactive_message_window_started_at DATETIME NULL`; migration backfills old rows before making the count non-null.

- [ ] **Step 4: Send iLink reminders through the Bot and update state only on success**

```python
def send_ilink_text(provider_account_id: str, ilink_user_id: str, content: str) -> str:
    response = httpx.post(
        f"{settings.WECHAT_BOT_SERVICE_URL.rstrip('/')}/v1/messages",
        headers={"X-Internal-Token": settings.WECHAT_BOT_INTERNAL_TOKEN},
        json={"provider_account_id": provider_account_id, "ilink_user_id": ilink_user_id, "content": content},
        timeout=settings.WECHAT_BOT_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return str(response.json().get("status") or "failed")
```

For iLink accounts, quota/window/session results increment `paused`; ordinary errors increment `failed`. Only `success` updates the count and `last_reminder_sent_at`. Inbound interaction resets the count and starts a new proactive window.

- [ ] **Step 5: Run reminder, migration, and script tests**

Run: `cd studybuddy-backend && pytest -q tests/unit/test_wechat_service.py tests/unit/test_ensure_wechat_tables_script.py tests/unit/test_dispatch_wechat_parent_reminders_script.py`

Expected: all selected tests PASS.

### Task 4: Integrated Verification And Documentation

**Files:**
- Modify: `docs/requirements/09-微信H5错题学习MVP与持久登录.md`
- Modify: `docs/开发进度文档.md`
- Modify: `docs/真人验收指南.md`

**Interfaces:**
- Consumes: Tasks 1-3 plus the shared-Bot student increment.
- Produces: current implementation status and exact human acceptance steps.

- [ ] **Step 1: Run all focused and full automated checks**

Run:

```bash
PYTHONPATH=. wechat_bot_service/.venv/bin/pytest -q wechat_bot_service/tests
cd studybuddy-backend && pytest -q
cd ../studybuddy-client && npm test -- --run && npm run lint && npm run typecheck && npm run build
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 2: Verify the local browser flows in the user's main Chrome**

Check desktop and 390px mobile layouts for account binding, parent invitation, and H5 login. Confirm QR refresh, countdown, bound/expired states, no overlap, no horizontal overflow, and no console errors.

- [ ] **Step 3: Run the two-WeChat human isolation flow**

Confirm both scans return the same Bot ID and different user IDs; each binding code, inbound reply, context token, and login link stays with its own user. Then bind an existing parent, run `今日学情`, set reminders, receive one due summary, and run `关闭提醒`.

- [ ] **Step 4: Update progress and acceptance documents with observed evidence only**

Record automated, browser, deployment, and human verification separately. Do not mark deployment or two-user verification complete unless actually observed.

- [ ] **Step 5: Review the complete diff without committing**

Run: `git status --short && git diff --stat && git diff --check`

Expected: only the shared Bot MVP files are changed, with no `.env`, credentials, QR images, logs, or `.playwright-cli/` artifacts.
