# Daily Review Yesterday/Today Design

## Goal

Fix Daily Review semantics so the student records **昨日回顾 + 今日目标** instead of “今天总结 + 明天目标”, while keeping the first version lightweight, testable, and compatible with the current notes-based storage.

## Background

The current page title and content format are confusing:

- Page shows text like `2026.7.5 总结 / 2026.7.6 目标`.
- The real desired habit is: summarize yesterday, set goals for today.
- The Agent has previously treated a target date inside a review as the current date.
- If the student has not written today’s review, the Agent should proactively remind them to write it.

## Product Decision

Daily Review and Study Plan stay separate but linked:

- Daily Review records lightweight reflection, current intent, and family督促 signal.
- Study Plan records executable tasks with time and completion state.
- Today goals in Daily Review may later generate a study-plan draft, but the student must confirm before any plan is saved.

## User Experience

Student page `/daily-review`:

- Header copy uses “昨日回顾 / 今日目标”.
- Default dates use the user/browser current date:
  - review date defaults to yesterday.
  - target date defaults to today.
- The dates are selectable.
- The summary field label is “昨日回顾”.
- The goals section label is “今日目标”.
- Today goals are edited as a checklist-style list, not one large paragraph.
- The page can still save support text as “需要督促的地方”.
- Saving creates one confirmed note and then navigates to note detail, preserving current behavior.

## Data Format

Do not add a new database table in this PR.

Continue storing Daily Review as a confirmed note:

- `category`: `每日回顾`
- `source`: `每日回顾`
- `knowledge_tags`: include `每日回顾` and `目标`
- `title`: `<targetDateLabel> 每日回顾`

Markdown content format:

```markdown
## 昨日回顾（2026.7.4）

背了 30 个英语单词，复盘了 2 道数学错题。

## 今日目标（2026.7.5）

- [ ] 背英语单词 20 个
- [ ] 做数学错题 2 道

## 需要督促的地方

下午开始前容易拖延，希望先提醒我打开书。
```

Checklist items are plain Markdown task-list items. This keeps notes readable and allows later parsing without a migration.

## Agent Behavior

When building student profile context:

- Include current server date using `date.today().isoformat()`.
- Parse Daily Review notes enough to detect whether there is a note for today’s target date.
- If no Daily Review targets today, append a concise reminder signal to context, for example:
  - `今日每日回顾：尚未填写，回答时可以温和提醒学生先补“昨日回顾 + 今日目标”。`
- When previewing recent Daily Review content, keep using a short summary and do not infer today from the note’s goal date.

No live LLM change is required in this PR, but unit tests must prove the deterministic context includes the reminder when missing and does not mis-label dates.

## Non-Goals

- Do not add微信提醒 or external push.
- Do not create study plans automatically from Daily Review.
- Do not add a graph database, vector store, or Mem0.
- Do not migrate existing Daily Review notes.
- Do not redesign unrelated pages.

## Acceptance Criteria

- Frontend tests cover:
  - page copy shows “昨日回顾 / 今日目标”.
  - default content on `2026-07-05` saves review date `2026.7.4` and target date `2026.7.5`.
  - goal input saves Markdown checklist items.
  - date selectors can change review/target dates.
- Backend tests cover:
  - Agent context includes recent Daily Review notes.
  - Agent context includes a missing-today-review reminder when today has no target-date review.
  - Agent context does not treat a future target date as server today.
- Help/update notes mention the Daily Review semantic fix.
- Codex browser验收 covers `/daily-review` as the student user.
