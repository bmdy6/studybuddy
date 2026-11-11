# 主会话状态持久化 + 跑题引导 实施计划

> **For agentic workers:** 用 superpowers:executing-plans 内联执行。步骤用 `- [ ]` 跟踪。

**Goal:** 修主会话/计划会话切换刷新丢失上下文的根因，并让计划会话跑题时 AI 友好引导回主会话建新计划。

**Architecture:** 不改数据库（MySQL 5.7 够）。前端：init 优先选主会话 + 导航状态按学生隔离持久化到 localStorage + "今天/学习中"从 activeTaskSessionId 推导不单独存 + 会话列表区分主/计划。后端：task prompt 跑题时调 present_choice_question 弹"去制定新计划/继续当前任务"；选项加 action 标记，前端识别 action 执行切回主会话+预填。

**Tech Stack:** React+Zustand+AntD（前端），FastAPI+MiMo（后端），pytest+vitest（测试）

**分支:** `feat/session-state`（worktree `.worktrees/feat-session-state`）

## Global Constraints
- MySQL 5.7 不换 PG。前后端不复制业务逻辑，复用同一 service。
- 前端命名 camelCase，后端 snake_case。禁魔法值，阈值提常量。
- 真机验收手机端 390×844（禁桌面端冒充），用 ego-browser DOM 断言，不读图。
- 不破坏 D1（切换不丢上下文）：只补刷新场景。
- 跑题口径不变（D3：换任务/换科目/同科目延伸算跑题，回主会话建新计划）。

## File Structure
- `studybuddy-client/src/features/chat/store.ts`：init 选会话 + 导航状态持久化读写
- `studybuddy-client/src/features/chat/sessionNav.ts`（新）：localStorage 读写工具，按 studentId 隔离
- `studybuddy-client/src/features/chat/hooks/useStudentLearningFlow.ts`：mode 从 activeTaskSessionId 推导
- `studybuddy-client/src/features/chat/components/ChatSessionToolbar.tsx`：会话列表区分主/计划
- `studybuddy-client/src/features/chat/pages/ChatPage.tsx`：onSendOption 识别 action
- `studybuddy-backend/app/prompts/agent/system_task.md`：跑题调 present_choice_question
- `studybuddy-backend/app/features/agent/tools.py`：present_choice_question schema 加 action/prefill 字段
- 测试：`studybuddy-client/src/test/chatStore.test.ts`、`studybuddy-client/src/test/ChatPage.test.tsx`、后端 prompt 相关

---

## 阶段一：状态层 P0（先做先验收）

### Task 1: 导航状态持久化工具 sessionNav.ts

**Files:**
- Create: `studybuddy-client/src/features/chat/sessionNav.ts`
- Test: `studybuddy-client/src/test/chatStore.test.ts`（加用例）

**Interfaces:**
- Produces: `saveNavState(studentId, {sessionId, activeTaskSessionId, mainSessionId})`、`loadNavState(studentId)`、`clearNavState(studentId)`
- localStorage key: `studybuddy-nav-<studentId>`

- [ ] **Step 1: 写 sessionNav.ts**

```typescript
// studybuddy-client/src/features/chat/sessionNav.ts
// 导航状态（当前会话/是否在计划/主会话id）按学生隔离持久化。
// 只存导航态，不存消息/流式运行态（刷新后流已断、靠 getMessages 重载）。

interface NavState {
  sessionId: number | null;
  activeTaskSessionId: number | null;
  mainSessionId: number | null;
}

function navKey(studentId: number): string {
  return `studybuddy-nav-${studentId}`;
}

export function saveNavState(studentId: number, state: NavState): void {
  try {
    localStorage.setItem(navKey(studentId), JSON.stringify(state));
  } catch {
    // localStorage 不可用时仅本会话静默
  }
}

export function loadNavState(studentId: number): NavState | null {
  try {
    const raw = localStorage.getItem(navKey(studentId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as NavState;
    if (typeof parsed.sessionId !== 'number' && parsed.sessionId !== null) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearNavState(studentId: number): void {
  try {
    localStorage.removeItem(navKey(studentId));
  } catch {
    // 静默
  }
}
```

- [ ] **Step 2: 写持久化工具单测**（加到 chatStore.test.ts）

```typescript
import { saveNavState, loadNavState, clearNavState } from '@/features/chat/sessionNav';

describe('sessionNav', () => {
  afterEach(() => localStorage.clear());

  it('save/load 按学生隔离', () => {
    saveNavState(1, { sessionId: 100, activeTaskSessionId: 200, mainSessionId: 100 });
    saveNavState(2, { sessionId: 300, activeTaskSessionId: null, mainSessionId: 300 });
    expect(loadNavState(1)?.sessionId).toBe(100);
    expect(loadNavState(1)?.activeTaskSessionId).toBe(200);
    expect(loadNavState(2)?.sessionId).toBe(300);
    expect(loadNavState(2)?.activeTaskSessionId).toBeNull();
  });

  it('clear 只清指定学生', () => {
    saveNavState(1, { sessionId: 100, activeTaskSessionId: null, mainSessionId: 100 });
    saveNavState(2, { sessionId: 200, activeTaskSessionId: null, mainSessionId: 200 });
    clearNavState(1);
    expect(loadNavState(1)).toBeNull();
    expect(loadNavState(2)?.sessionId).toBe(200);
  });

  it('load 无数据返回 null', () => {
    expect(loadNavState(999)).toBeNull();
  });
});
```

- [ ] **Step 3: 跑测试确认通过**

Run: `cd studybuddy-client && npx vitest run src/test/chatStore.test.ts -t "sessionNav"`
Expected: PASS

---

### Task 2: init 优先选主会话 + 恢复持久化状态

**Files:**
- Modify: `studybuddy-client/src/features/chat/store.ts`（init）
- Test: `studybuddy-client/src/test/chatStore.test.ts`

**Interfaces:**
- Consumes: `loadNavState/saveNavState/clearNavState` from sessionNav
- init 逻辑：先 loadNavState -> 若记的 sessionId 还在 sessions 列表 -> switchSession 它；否则优先选 session_type==='main' -> fallback 第一个

- [ ] **Step 1: 写失败测试——init 优先选 main 会话不选 task**

```typescript
it('init 学生优先选 session_type=main 的主会话，不选 task', async () => {
  // mock chatApi.listSessions 返回：task 在前（updated_at 最新），main 在后
  const sessions = [
    { id: 200, user_id: 1, student_id: 1, title: '学习任务', created_at: '', session_type: 'task', plan_id: 10, plan_item_id: 5, status: 'active' },
    { id: 100, user_id: 1, student_id: 1, title: '学习对话', created_at: '', session_type: 'main', plan_id: null, plan_item_id: null, status: 'active' },
  ];
  vi.mocked(chatApi.listSessions).mockResolvedValue(sessions);
  vi.mocked(chatApi.getMessages).mockResolvedValue([]);
  useChatStore.getState().reset();
  await useChatStore.getState().init({ token: 't', role: 'student', userId: 1, requestedStudentId: null, activeChildId: null });
  expect(useChatStore.getState().sessionId).toBe(100); // 选 main(100) 不选 task(200)
});
```

- [ ] **Step 2: 写失败测试——init 恢复持久化的 task session**

```typescript
it('init 恢复持久化的会话位置（task session）', async () => {
  saveNavState(1, { sessionId: 200, activeTaskSessionId: 200, mainSessionId: 100 });
  const sessions = [
    { id: 200, user_id: 1, student_id: 1, title: '学习任务', created_at: '', session_type: 'task', plan_id: 10, plan_item_id: 5, status: 'active' },
    { id: 100, user_id: 1, student_id: 1, title: '学习对话', created_at: '', session_type: 'main', plan_id: null, plan_item_id: null, status: 'active' },
  ];
  vi.mocked(chatApi.listSessions).mockResolvedValue(sessions);
  vi.mocked(chatApi.getMessages).mockResolvedValue([]);
  useChatStore.getState().reset();
  await useChatStore.getState().init({ token: 't', role: 'student', userId: 1, requestedStudentId: null, activeChildId: null });
  // 恢复到记住的 task 200，不是回 main 100
  expect(useChatStore.getState().sessionId).toBe(200);
  expect(useChatStore.getState().activeTaskSessionId).toBe(200);
  expect(useChatStore.getState().mainSessionId).toBe(100);
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd studybuddy-client && npx vitest run src/test/chatStore.test.ts -t "init"`
Expected: FAIL（现状选 task 200）

- [ ] **Step 4: 改 init 实现**

在 `store.ts` init 中，`refreshSessions` 后改为：
```typescript
await get().refreshSessions();
const list = get().sessions;
// 1. 优先恢复持久化位置（刷新回到原处，不踢回主会话）
const studentIdForNav = ctx.role === 'student' ? ctx.userId : (ctx.requestedStudentId ?? ctx.activeChildId);
const saved = studentIdForNav ? loadNavState(studentIdForNav) : null;
const savedExists = saved?.sessionId && list.some((s) => s.id === saved.sessionId);
if (savedExists) {
  set({
    sessionId: saved!.sessionId,
    _activeSessionId: saved!.sessionId,
    activeTaskSessionId: saved!.activeTaskSessionId,
    mainSessionId: saved!.mainSessionId,
  });
  await get().switchSession(saved!.sessionId!);
  return;
}
// 2. 记不住 -> 学生优先选 main 主会话，不选 task
const preferredSession =
  ctx.role === 'student'
    ? list.find((s) => s.student_id === ctx.userId && s.session_type === 'main')
      ?? list.find((s) => s.student_id === ctx.userId)
    : ctx.requestedStudentId
      ? list.find((s) => s.student_id === ctx.requestedStudentId)
      : list[0];
if (preferredSession) {
  await get().switchSession(preferredSession.id);
} else {
  await get().newSession();
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd studybuddy-client && npx vitest run src/test/chatStore.test.ts -t "init"`
Expected: PASS

---

### Task 3: 切换/进入/返回时写持久化

**Files:**
- Modify: `studybuddy-client/src/features/chat/store.ts`（switchSession/continueTaskItem/returnToMainSession/newSession/reset）

- [ ] **Step 1: 写失败测试——switchSession 后写持久化**

```typescript
it('switchSession 后写持久化', async () => {
  vi.mocked(chatApi.getMessages).mockResolvedValue([]);
  useChatStore.getState().reset();
  await useChatStore.getState().init({ token: 't', role: 'student', userId: 1, requestedStudentId: null, activeChildId: null });
  // init 已选 main 100（见 Task2 mock）
  await useChatStore.getState().switchSession(100);
  const saved = loadNavState(1);
  expect(saved?.sessionId).toBe(100);
});
```

- [ ] **Step 2: 跑确认失败**

Run: `cd studybuddy-client && npx vitest run src/test/chatStore.test.ts -t "switchSession 后写"`
Expected: FAIL

- [ ] **Step 3: 在 switchSession/continueTaskItem/returnToMainSession/newSession 末尾加 saveNavState**

封装一个内部 helper：
```typescript
function persistNav(set: any, get: any) {
  const sid = get()._boundStudentId;
  if (!sid) return;
  saveNavState(sid, {
    sessionId: get().sessionId,
    activeTaskSessionId: get().activeTaskSessionId,
    mainSessionId: get().mainSessionId,
  });
}
```
在 `switchSession` finally 后、`continueTaskItem` 拿到 taskSession 后、`returnToMainSession` 后、`newSession` 后调 `persistNav(set, get)`。
在 `reset` 里：若 `_boundStudentId` 存在则 `clearNavState`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd studybuddy-client && npx vitest run src/test/chatStore.test.ts`
Expected: PASS

---

### Task 4: mode 从 activeTaskSessionId 推导（不依赖组件 useState）

**Files:**
- Modify: `studybuddy-client/src/features/chat/hooks/useStudentLearningFlow.ts`
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`（传 activeTaskSessionId）

**问题**：mode 在 useStudentLearningFlow 的 useState，刷新重置为 'today'。即使 store 恢复了 activeTaskSessionId，mode 还是 today -> 不显示"返回今天"按钮。
**解法**：mode 从 store 的 activeTaskSessionId 推导（非空=learning），不再单独 useState。setMode 仍保留用于即时切换（点继续学习/返回今天），但初始值从 store 推。

- [ ] **Step 1: 改 useStudentLearningFlow，mode 初始值从 activeTaskSessionId 推导**

```typescript
// useStudentLearningFlow 加参数 activeTaskSessionId
export function useStudentLearningFlow({
  ...,
  activeTaskSessionId,  // 新增
}: UseStudentLearningFlowOptions & { activeTaskSessionId: number | null }) {
  const [mode, setMode] = useState<'today' | 'learning'>(
    activeTaskSessionId ? 'learning' : 'today'
  );
  // ...其余不变，但 startLearning/returnToToday 仍 setMode
}
```

- [ ] **Step 2: ChatPage 传 activeTaskSessionId 给 hook**

```typescript
const activeTaskSessionId = useChatStore((s) => s.activeTaskSessionId);
const studentLearning = useStudentLearningFlow({ ..., activeTaskSessionId });
```

- [ ] **Step 3: 跑前端全量测试 + typecheck**

Run: `cd studybuddy-client && npx vitest run && npm run typecheck`
Expected: PASS

---

### Task 5: 状态层真机验收（本地手机视口）

- [ ] **Step 1: 启动 worktree 前后端**

Run: `cd .worktrees/feat-session-state/studybuddy-backend && .venv/bin/uvicorn app.main:app --port 8002 &` + `cd .worktrees/feat-session-state/studybuddy-client && npm run dev -- --port 5174 &`
（用 8002/5174 避开主目录在跑的 8001/5173）

- [ ] **Step 2: ego-browser DOM 断言验收 5 步路径**（390×844，不读图）
1. 登录 student -> /chat
2. 点"继续学习"进 task session -> 探查 activeTaskSessionId、返回按钮在
3. 刷新 -> 探查 sessionId 仍是 task、返回按钮仍在、历史在
4. 点"返回今天" -> 切回主会话、历史完整
5. 主会话刷新 -> 还在主会话不跳 task

- [ ] **Step 3: 验收通过后 commit 状态层**

```bash
git add -A && git commit -m "feat: 主会话状态持久化（init优先选主会话+导航态按学生隔离持久化+mode从task推导）"
```

---

## 阶段二：跑题引导 P1（依赖阶段一）

### Task 6: present_choice_question schema 加 action/prefill

**Files:**
- Modify: `studybuddy-backend/app/features/agent/tools.py`（_TOOL_PRESENT_CHOICE_QUESTION schema）
- Modify: `studybuddy-backend/app/features/agent/handlers/interaction.py`（透传 action/prefill）

**Interfaces:**
- option 加可选字段 `action: "return_to_main"`、`prefill: string`

- [ ] **Step 1: schema option 加 action/prefill 可选字段**

```python
# tools.py _TOOL_PRESENT_CHOICE_QUESTION input_schema.options.items.properties 加：
"action": {"type": "string", "enum": ["return_to_main"], "description": "前端动作标记：return_to_main=切回主会话+预填"},
"prefill": {"type": "string", "description": "action=return_to_main 时填入主会话输入框的预填文本"},
```

- [ ] **Step 2: handler 透传 action/prefill 到 tool_result**

```python
# interaction.py _handle_present_choice_question 返回的 options 保留 action/prefill
```

- [ ] **Step 3: 后端测试**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest tests/ -k "present_choice" -q`
Expected: PASS

---

### Task 7: 前端 onSendOption 识别 action 切回主会话+预填

**Files:**
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`（onSendOption）
- Modify: `studybuddy-client/src/features/chat/components/MessageBubble.tsx`（option 传 action/prefill 到 onPickOption）
- Modify: `studybuddy-client/src/types/chat.ts`（option 类型加 action/prefill）

- [ ] **Step 1: 类型加 action/prefill**

```typescript
// types/chat.ts option 类型
{ label: string; value: string; action?: 'return_to_main'; prefill?: string }
```

- [ ] **Step 2: MessageBubble onPickOption 传完整 option**

改 `onPickOption?: (value: string, label?: string, option?: { action?: string; prefill?: string }) => void`，handlePick 调 `onPick?.(value, label, opt)`。

- [ ] **Step 3: ChatPage onSendOption 识别 action**

```typescript
onSendOption={(value, label, option) => {
  if (option?.action === 'return_to_main') {
    void useChatStore.getState().returnToMainSession().then(() => {
      setInput(option.prefill ?? value);
      inputRef.current?.focus();
    });
    return;
  }
  void handleSend(value, label);
}}
```

- [ ] **Step 4: 前端测试 + typecheck**

Run: `cd studybuddy-client && npx vitest run && npm run typecheck`
Expected: PASS

---

### Task 8: task prompt 跑题调 present_choice_question

**Files:**
- Modify: `studybuddy-backend/app/prompts/agent/system_task.md`

- [ ] **Step 1: 改 prompt**

```
- 跑题时不要只用文字引导。调 present_choice_question 弹两个选项：
  1. label="去制定新计划" value="new_plan" action="return_to_main" prefill="<学生原话，如'我想做数学'>"
  2. label="继续当前任务" value="continue"
  调用前先用一句话说明，例如"好，这个回主会话帮你安排"。不要在任务会话里教计划外内容、不要当场建新计划。
```

- [ ] **Step 2: 后端全量测试**

Run: `cd studybuddy-backend && .venv/bin/python -m pytest -q`
Expected: PASS

---

### Task 9: 跑题引导真机验收

- [ ] **Step 1: ego-browser 完整路径验收**（390×844，不读图）
1. 进数学计划 task session
2. 发"我想做英语阅读"
3. 探查：AI 回复 + present_choice_question 工具卡，两个按钮【去制定新计划】【继续当前任务】
4. 点【去制定新计划】
5. 探查：切回主会话、输入框预填"我想做英语阅读"
6. 点发送 -> 主会话 AI 开始安排英语计划
7. 点【继续当前任务】验证留在 task

- [ ] **Step 2: 验收通过 commit 跑题引导**

```bash
git add -A && git commit -m "feat: 计划会话跑题友好引导（AI弹按钮切回主会话+预填意图）"
```

---

### Task 10: 合并 main + 公网验收

- [ ] **Step 1: rebase 最新 main**

Run: `cd .worktrees/feat-session-state && git fetch origin && git rebase origin/main`

- [ ] **Step 2: 部署** `scripts/deploy_all.sh`（确认无其他 session 在部署）

- [ ] **Step 3: 公网手机端验收** 5+7 步路径，报告 URL/账号/视口/id/观察

- [ ] **Step 4: 用户确认 OK 后合并 main + push，标文档 [已验收]**

## Verification
- 前端：`cd studybuddy-client && npm run lint && npx vitest run && npm run typecheck && npm run build`
- 后端：`cd studybuddy-backend && .venv/bin/python -m pytest -q`
- 真机：390×844 ego-browser DOM 断言，状态层 5 步 + 跑题引导 7 步
- 公网：部署后公网 URL 复验
