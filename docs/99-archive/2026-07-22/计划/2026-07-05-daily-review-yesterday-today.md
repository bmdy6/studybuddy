# Daily Review Yesterday/Today Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change Daily Review from “今天总结 / 明天目标” to “昨日回顾 / 今日目标”, add checklist goals and Agent missing-review reminder.

**Architecture:** Keep using notes as the storage layer. Frontend builds deterministic Markdown with selected review/target dates. Backend Agent context parses recent Daily Review notes and adds a deterministic reminder signal when today has no Daily Review target.

**Tech Stack:** React 18, AntD 5, Vitest, FastAPI, SQLAlchemy, pytest.

## Global Constraints

- Create a new branch from latest `main`; do not commit to `main`.
- Branch name: `fix/daily-review-yesterday-today`.
- One PR only, focused on Daily Review semantics.
- Do not add a database table or migration.
- Do not auto-create study plans.
- Reuse existing `noteApi`, `DailyReviewPage`, note service and Agent context code.
- Keep PR below 30 files.
- Commit messages must be simple Chinese.

---

## File Structure

- Modify `studybuddy-client/src/pages/DailyReviewPage.tsx`: UI copy, date selectors, checklist-style goal editing, Markdown builder.
- Modify `studybuddy-client/src/test/DailyReviewPage.test.tsx`: update and add frontend behavior tests.
- Modify `studybuddy-backend/app/core/agent_loop.py`: deterministic Daily Review context helper/reminder.
- Modify `studybuddy-backend/tests/unit/test_agent_loop.py`: add Agent context tests.
- Modify `studybuddy-client/src/data/releaseNotes.ts`: add help/update note.

## Task 1: Frontend Daily Review Semantics

**Files:**
- Modify: `studybuddy-client/src/pages/DailyReviewPage.tsx`
- Test: `studybuddy-client/src/test/DailyReviewPage.test.tsx`

**Interfaces:**
- Consumes: existing `noteApi.create`, `noteApi.update`, `noteApi.list`.
- Produces: confirmed note content in Markdown format described by the spec.

- [ ] Update tests first:
  - Freeze time at `2026-07-05T09:00:00+08:00`.
  - Assert the page shows `昨日回顾 / 今日目标`.
  - Assert field labels include `昨日回顾` and `今日目标`.
  - Assert saving creates title `2026.7.5 每日回顾`.
  - Assert content contains `## 昨日回顾（2026.7.4）`.
  - Assert content contains `## 今日目标（2026.7.5）`.
  - Assert goals are saved as checklist lines such as `- [ ] 背英语单词 20 个`.
  - Add one test that changes review date and target date and verifies saved content uses selected dates.

- [ ] Run the frontend test and confirm it fails before implementation:

```bash
cd studybuddy-client
npm test -- DailyReviewPage.test.tsx --run
```

- [ ] Implement the page change:
  - Replace `today`/`nextLabel` with `reviewDate` and `targetDate`.
  - Default `reviewDate` to yesterday and `targetDate` to today.
  - Use AntD `DatePicker` for both date fields.
  - Store goals as an editable multiline text area, but convert non-empty lines into Markdown checklist items on save.
  - Keep support text optional.
  - Validation messages should say `写一点昨日回顾` and `写一点今日目标`.

- [ ] Re-run the frontend test and make it pass:

```bash
cd studybuddy-client
npm test -- DailyReviewPage.test.tsx --run
```

## Task 2: Agent Context Reminder

**Files:**
- Modify: `studybuddy-backend/app/core/agent_loop.py`
- Test: `studybuddy-backend/tests/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: existing `note_service.list_notes(db, student_id)`.
- Produces: `_build_profile_context(db, student_id)` includes deterministic Daily Review reminder when needed.

- [ ] Add backend tests first:
  - Existing Daily Review note with `## 今日目标（2026.7.5）` should count as today when server date is patched to `2026-07-05`.
  - Existing note with only `## 今日目标（2026.7.6）` should not count as today when server date is patched to `2026-07-05`.
  - Missing today should add reminder text containing `尚未填写` and `昨日回顾 + 今日目标`.

- [ ] Run the backend unit test and confirm it fails before implementation:

```bash
cd studybuddy-backend
.venv/bin/python -m pytest tests/unit/test_agent_loop.py::TestDailyReviewContext -q
```

- [ ] Implement helper logic in `agent_loop.py`:
  - Add a small helper to parse target dates from Daily Review note content and title.
  - Use `date.today()` as the only current-date anchor.
  - Append missing-review reminder only when no parsed target date equals today.
  - Keep preview truncation behavior.

- [ ] Re-run the backend unit test:

```bash
cd studybuddy-backend
.venv/bin/python -m pytest tests/unit/test_agent_loop.py::TestDailyReviewContext -q
```

## Task 3: Help Update and PR

**Files:**
- Modify: `studybuddy-client/src/data/releaseNotes.ts`

**Interfaces:**
- Produces: user-visible update note under Help/Updates.

- [ ] Add a release note at the top:
  - title: `每日回顾语义修复`
  - mention `昨日回顾 / 今日目标`
  - mention 今日目标 checklist
  - mention Agent will use missing Daily Review signal to remind the student.

- [ ] Run focused verification:

```bash
cd studybuddy-client
npm test -- DailyReviewPage.test.tsx HelpPage.test.tsx --run
cd ../studybuddy-backend
.venv/bin/python -m pytest tests/unit/test_agent_loop.py::TestDailyReviewContext -q
```

- [ ] Run broader pre-PR verification if focused tests pass:

```bash
cd studybuddy-client
npm run typecheck
npm run lint
npm run build
```

- [ ] Commit with a simple Chinese message:

```bash
git add studybuddy-client/src/pages/DailyReviewPage.tsx studybuddy-client/src/test/DailyReviewPage.test.tsx studybuddy-client/src/data/releaseNotes.ts studybuddy-backend/app/core/agent_loop.py studybuddy-backend/tests/unit/test_agent_loop.py
git commit -m "修复每日回顾日期语义"
```

- [ ] Push and create PR:

```bash
git push -u origin fix/daily-review-yesterday-today
gh pr create --title "修复每日回顾日期语义" --body-file /tmp/daily-review-pr.md
```

PR body must include:

- What changed.
- Why it changed.
- Behavior changes.
- Risk points.
- Exact test commands and results.
- Note that Codex still needs browser验收 before merge.
