# 笔记页默认显示全部笔记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `/notes` 默认只显示“未分类”导致笔记页空白的问题。

**Architecture:** 只改前端 `NotesPage` 的筛选状态语义：`activeCategory=null` 表示全部。新增一个前端单测覆盖默认全部和分类筛选。

**Tech Stack:** React 18, AntD 5, Vitest, Testing Library.

## Global Constraints

- 不改后端 notes API。
- 不重做笔记页整体视觉。
- 提交控制在 1-3 个文件。

---

### Task 1: NotesPage 默认全部视图

**Files:**
- Modify: `studybuddy-client/src/pages/NotesPage.tsx`
- Create: `studybuddy-client/src/test/NotesPage.test.tsx`

**Interfaces:**
- Consumes: `noteApi.list(studentId?)`, `noteApi.blindSpots(studentId?)`
- Produces: `activeCategory=null` means all notes

- [ ] **Step 1: Write failing tests**

Create `studybuddy-client/src/test/NotesPage.test.tsx` with two tests:

```tsx
it('默认展示全部分类的笔记', async () => {
  mockList.mockResolvedValue([
    { id: 1, title: '7.5 每日回顾', category: '每日回顾', subject: '其他', status: 'confirmed', source: '每日回顾', content: '', knowledge_tags: [], updated_at: '2026-07-05' },
    { id: 2, title: '英语错题复盘', category: '错题复盘', subject: '英语', status: 'confirmed', source: 'agent', content: '', knowledge_tags: [], updated_at: '2026-07-05' },
  ]);
  mockBlindSpots.mockResolvedValue([]);
  render(<MemoryRouter><App><NotesPage /></App></MemoryRouter>);
  expect(await screen.findByText('7.5 每日回顾')).toBeInTheDocument();
  expect(await screen.findByText('英语错题复盘')).toBeInTheDocument();
});

it('点击分类后只展示该分类', async () => {
  // same setup
  fireEvent.click(await screen.findByText('每日回顾'));
  expect(screen.getByText('7.5 每日回顾')).toBeInTheDocument();
  expect(screen.queryByText('英语错题复盘')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd studybuddy-client && npm test -- NotesPage.test.tsx --run
```

Expected: first test fails because default filtered list only shows uncategorized notes.

- [ ] **Step 3: Implement minimal fix**

In `NotesPage.tsx`:

```tsx
const filteredNotes = useMemo(
  () => (activeCategory ? notes.filter((n) => (n.category || '未分类') === activeCategory) : notes),
  [notes, activeCategory],
);
```

Add an “全部” `Tag.CheckableTag` before category tags and set `activeCategory` to `null` when clicked.

- [ ] **Step 4: Verify**

Run:

```bash
cd studybuddy-client && npm test -- NotesPage.test.tsx --run
cd studybuddy-client && npm run lint
cd studybuddy-client && npm run typecheck
cd studybuddy-client && npm run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Browser acceptance**

Open `/notes` with student account in Codex browser. Expected: list page shows all notes by default, and category chips can narrow the list.

- [ ] **Step 6: Commit**

```bash
git add studybuddy-client/src/pages/NotesPage.tsx studybuddy-client/src/test/NotesPage.test.tsx
git commit -m "修复笔记页默认空白"
```
