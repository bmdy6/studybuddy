# ChatPage Split Implementation Plan

> **For agentic workers:** Choose superpowers:subagent-driven-development for multiple independent tasks with the required Git authorization; otherwise use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `ChatPage.tsx` into focused chat-domain components and hooks without changing API calls, user-visible behavior, or styling.

**Architecture:** Keep `ChatPage` as the orchestration layer. Move self-contained rendering into `features/chat/components`, upload workflows into one chat-domain hook, and student learning entry state into one hook. Reuse the existing store, APIs, Ant Design forms, CSS classes, and behavior tests.

**Tech Stack:** React 18, TypeScript, Ant Design 5, Zustand, Vitest, Testing Library.

## Global Constraints

- Do not change business logic, API paths, user-facing copy, or CSS behavior.
- Keep `ChatPage.tsx` below 400 lines and each extracted component/hook below 300 lines.
- Preserve the existing 27 `ChatPage` characterization tests throughout the refactor.
- Do not modify `package.json`, `package-lock.json`, dependencies, or deployment configuration.
- Do not commit, push, merge, or deploy without separate authorization.

---

### Task 1: Extract Leaf Presentation Components

**Files:**
- Create: `studybuddy-client/src/features/chat/components/ErrorReportCard.tsx`
- Create: `studybuddy-client/src/features/chat/components/BatchUploadModal.tsx`
- Create: `studybuddy-client/src/features/chat/components/MaterialUploadModal.tsx`
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`
- Test: `studybuddy-client/src/test/ChatPage.test.tsx`

**Interfaces:**
- `ErrorReportCard({ report, onCopy, onClose })`
- `BatchUploadModal({ open, files, uploading, error, form, onCancel, onConfirm })`
- `MaterialUploadModal({ open, file, uploading, form, onCancel, onConfirm })`

- [ ] **Step 1: Run the existing characterization suite**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx`
Expected: 27 tests pass.

- [ ] **Step 2: Move the existing JSX without changing props, copy, or handlers**

Use typed props and existing Ant Design `FormInstance` values. Keep API calls and state in `ChatPage` for this step.

- [ ] **Step 3: Re-run the characterization suite**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx`
Expected: 27 tests pass.

- [ ] **Step 4: Review the working-tree diff**

Run: `git diff --check && git diff --stat`
Expected: only the three new components and `ChatPage.tsx` change.

### Task 2: Extract Session Toolbar, Workbench, and Message List

**Files:**
- Create: `studybuddy-client/src/features/chat/components/ChatSessionToolbar.tsx`
- Create: `studybuddy-client/src/features/chat/components/ParentLearningWorkbench.tsx`
- Create: `studybuddy-client/src/features/chat/components/ChatMessageList.tsx`
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`
- Test: `studybuddy-client/src/test/ChatPage.test.tsx`

**Interfaces:**
- `ChatSessionToolbar({ sessions, sessionId, onSwitch, onCreate, onRename, onDelete })`
- `ParentLearningWorkbench({ studentName, profileSummary, profilePromptDismissed, onPrompt, onEditProfile, onSnoozeProfile })`
- `ChatMessageList({ messages, loading, role, workbench, onSendOption, onRequestManualInput })`

- [ ] **Step 1: Extract the parent-only session toolbar and preserve menu semantics**
- [ ] **Step 2: Extract the parent empty-state workbench with the same task prompts and CSS classes**
- [ ] **Step 3: Extract message windowing and scroll behavior into `ChatMessageList`**
- [ ] **Step 4: Run the characterization suite after each extraction**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx`
Expected: 27 tests pass after every step.

### Task 3: Extract Upload Workflow Hook and Composer

**Files:**
- Create: `studybuddy-client/src/features/chat/hooks/useChatUploads.ts`
- Create: `studybuddy-client/src/features/chat/components/ChatComposer.tsx`
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`
- Test: `studybuddy-client/src/test/ChatPage.test.tsx`

**Interfaces:**
- `useChatUploads({ sessionId, loading, resolveStudentId, onSend, onError })` returns file selection refs/state, forms, loading flags, modal handlers, and confirm handlers.
- `ChatComposer` receives input state, send callback, pending confirmation panels, latest error report, and upload controls.

- [ ] **Step 1: Move upload state and existing API orchestration into `useChatUploads` without changing messages or cleanup behavior**
- [ ] **Step 2: Run upload-focused tests**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx -t "拍题|粘贴|上传失败"`
Expected: matching tests pass.

- [ ] **Step 3: Move the composer JSX into `ChatComposer`**
- [ ] **Step 4: Run the full characterization suite**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx`
Expected: 27 tests pass.

### Task 4: Extract Student Learning State and Finish Orchestrator

**Files:**
- Create: `studybuddy-client/src/features/chat/hooks/useStudentLearningFlow.ts`
- Modify: `studybuddy-client/src/features/chat/pages/ChatPage.tsx`
- Test: `studybuddy-client/src/test/ChatPage.test.tsx`

**Interfaces:**
- `useStudentLearningFlow({ token, role, studentId, input, setInput, onSend, inputRef })` returns the Today/learning mode, current entry, derived prompt, and panel callbacks.

- [ ] **Step 1: Move only the existing learning-entry fetch and mode callbacks into the hook**
- [ ] **Step 2: Run student-flow tests**

Run: `npm --prefix studybuddy-client run test -- --run src/test/ChatPage.test.tsx -t "学生|学习建议|完成任务"`
Expected: matching tests pass.

- [ ] **Step 3: Confirm file-size targets and dependency direction**

Run: `wc -l studybuddy-client/src/features/chat/pages/ChatPage.tsx studybuddy-client/src/features/chat/components/*.tsx studybuddy-client/src/features/chat/hooks/*.ts`
Expected: `ChatPage.tsx < 400`; every newly extracted file `< 300`.

### Task 5: Full Verification and Browser Acceptance

**Files:**
- Modify only if required by an observed regression.

- [ ] **Step 1: Run all frontend checks**

Run: `npm --prefix studybuddy-client run typecheck && npm --prefix studybuddy-client run lint && npm --prefix studybuddy-client run build && npm --prefix studybuddy-client run test`
Expected: all commands pass; Vitest count is at least the 194-test handoff baseline.

- [ ] **Step 2: Start the backend and frontend locally without reading `.env`**

Use the documented project commands and existing local configuration. Do not change dependencies or environment files.

- [ ] **Step 3: Exercise the real chat path in a browser**

Verify parent empty workbench, session switch/new conversation, send/stream response, student Today/learning transition, photo selection modal, material selection modal, error card close/copy, and desktop/mobile layout.

- [ ] **Step 4: Review final diff and residual risks**

Run: `git diff --check && git status --short && git diff --stat`
Expected: only chat-domain source files, the plan, and any explicitly justified tests/docs change.
