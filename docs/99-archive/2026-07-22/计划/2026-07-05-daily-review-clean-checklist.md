# Daily Review Clean Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify Daily Review to one editable review date with automatic target date and clickable checklist goals.

**Architecture:** Keep Daily Review as confirmed notes. Move target goals from raw multiline text to local `GoalItem[]` state in `DailyReviewPage`; derive target date from `reviewDate.add(1, 'day')`.

**Tech Stack:** React, Ant Design, dayjs, Vitest, Testing Library.

## Global Constraints

- Do not add backend tables or migrations.
- Do not add dependencies.
- Use existing design tokens in `studybuddy-client/src/index.css`.
- Goal date must always be exactly review date + 1 day.
- Completed goals save as Markdown task list `- [x]`.

---

### Task 1: Daily Review Checklist Tests

**Files:**
- Modify: `studybuddy-client/src/test/DailyReviewPage.test.tsx`

**Interfaces:**
- Consumes: `DailyReviewPage`, `buildDailyReviewContent`
- Produces: failing tests for automatic target date and goal completion.

- [x] Add a test asserting the page renders only `回顾日期`, not a separate editable `目标日期`.
- [x] Add a test asserting `buildDailyReviewContent` saves `- [x]` for completed goals.
- [x] Add a test clicking a goal item and asserting it gets a line-through style.
- [x] Run `npm test -- DailyReviewPage.test.tsx --run` and confirm the new assertions fail before implementation.

### Task 2: Daily Review UI Implementation

**Files:**
- Modify: `studybuddy-client/src/pages/DailyReviewPage.tsx`

**Interfaces:**
- Produces: `GoalItem` local state, automatic target date, clickable checklist.

- [x] Remove editable `targetDate` state.
- [x] Add `targetDate = reviewDate.add(1, 'day')`.
- [x] Replace multiline goal textarea with one-line goal input, add button, and checklist list.
- [x] Toggle goal completion on click and apply line-through to completed labels.
- [x] Save checklist to note content using `- [ ]` and `- [x]`.
- [x] Keep support text optional.

### Task 3: Release Notes and Verification

**Files:**
- Modify: `studybuddy-client/src/data/releaseNotes.ts`

**Interfaces:**
- Produces: visible help/update entry.

- [x] Add update note for simplified Daily Review and clickable goals.
- [x] Run focused tests, lint, typecheck, build.
- [x] Use Codex browser to verify `/daily-review` locally.
- [x] Commit with Chinese message and deploy.
