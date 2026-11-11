# Daily Review Plan Chat Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a student turn a Daily Review goal into a chat-based plan discussion without directly creating a study plan.

**Architecture:** Reuse the existing ChatPage `?prompt=` prefill behavior. DailyReviewPage builds a plan-discussion prompt from one goal and navigates to `/chat` with `student_id` and `prompt`.

**Tech Stack:** React, React Router, Ant Design, Vitest, Testing Library.

## Global Constraints

- Do not create a study plan directly from Daily Review.
- The prompt must require the Agent to discuss and confirm before creating a plan.
- Keep the UI compact and consistent with the existing Daily Review page.
- Use TDD: write the failing test before production code.

---

### Task 1: Daily Review Goal To Chat Entry

**Files:**
- Modify: `studybuddy-client/src/test/DailyReviewPage.test.tsx`
- Modify: `studybuddy-client/src/pages/DailyReviewPage.tsx`

**Interfaces:**
- Consumes: existing `navigate('/chat?...')` pattern.
- Produces: `buildGoalPlanPrompt(goalText: string): string`.

- [ ] **Step 1: Write failing tests**

Add two tests to `DailyReviewPage.test.tsx`:

```tsx
it('未完成目标可以跳转到对话页先商量计划', async () => {
  render(
    <MemoryRouter>
      <DailyReviewPage />
    </MemoryRouter>,
  );

  fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
    target: { value: '下午复习英语语法' },
  });
  fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
  fireEvent.click(screen.getByRole('button', { name: '商量计划：下午复习英语语法' }));

  expect(mockNavigate).toHaveBeenCalledTimes(1);
  const target = mockNavigate.mock.calls[0][0] as string;
  expect(target).toContain('/chat?');
  expect(target).toContain('student_id=2');
  expect(decodeURIComponent(target)).toContain('我今天的目标是：下午复习英语语法');
  expect(decodeURIComponent(target)).toContain('请先和我商量');
  expect(decodeURIComponent(target)).toContain('确认学习时长、任务拆分和可行性');
  expect(decodeURIComponent(target)).toContain('再帮我创建学习计划');
});

it('已完成目标不显示商量计划入口', async () => {
  render(
    <MemoryRouter>
      <DailyReviewPage />
    </MemoryRouter>,
  );

  fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
    target: { value: '完成英语单词复习' },
  });
  fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
  fireEvent.click(screen.getByRole('checkbox', { name: '完成英语单词复习' }));

  expect(screen.queryByRole('button', { name: '商量计划：完成英语单词复习' })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd studybuddy-client
npm test -- DailyReviewPage.test.tsx --run
```

Expected: tests fail because the “商量计划” button does not exist.

- [ ] **Step 3: Implement minimal code**

In `DailyReviewPage.tsx`:

```tsx
export function buildGoalPlanPrompt(goalText: string) {
  return `我今天的目标是：${goalText.trim()}。请先和我商量这个目标怎么安排，确认学习时长、任务拆分和可行性后，再帮我创建学习计划。`;
}
```

Add a handler:

```tsx
const openGoalPlanChat = (goal: GoalItem) => {
  const params = new URLSearchParams({
    student_id: String(studentId),
    prompt: buildGoalPlanPrompt(goal.text),
  });
  navigate(`/chat?${params.toString()}`);
};
```

Render a small button beside each incomplete goal:

```tsx
{!goal.done && (
  <Button
    size="small"
    type="link"
    aria-label={`商量计划：${goal.text}`}
    onClick={() => openGoalPlanChat(goal)}
  >
    商量计划
  </Button>
)}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
cd studybuddy-client
npm test -- DailyReviewPage.test.tsx ChatPage.test.tsx --run
npm run lint
npm run typecheck
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-06-daily-review-plan-chat-entry-design.md docs/superpowers/plans/2026-07-06-daily-review-plan-chat-entry.md
git commit -m "记录每日目标商量计划方案"
git add studybuddy-client/src/pages/DailyReviewPage.tsx studybuddy-client/src/test/DailyReviewPage.test.tsx
git commit -m "增加每日目标商量计划入口"
```
