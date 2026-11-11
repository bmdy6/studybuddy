# P1 Fixes Delivery Design

## Goal

Deliver the current P1 fixes for StudyBuddy so the online app is usable by the student without the latest real-use blockers:

1. Daily Review uses the correct “昨日回顾 + 今日目标” semantics.
2. Photo-based homework grading has a clear MVP flow that grades first and then stores learning assets.
3. Material preview links work online and do not open the old Visionary app.
4. Switching accounts refreshes user-scoped data automatically.

This spec defines the product boundaries, architecture, tests, browser acceptance criteria, documentation updates, and deployment gates for the P1 delivery.

## Background

Recent real-user testing exposed four P1 issues:

- Daily Review date semantics are confusing. The Agent previously treated a target date inside a review as the real current date.
- The student used the material upload path for a homework photo. The Agent summarized the image as study material instead of grading each question and giving correct answers.
- Online material links such as `/uploads/materials/...jpg` are routed to an old Visionary web app because the public reverse-proxy prefix should be `/sb/uploads/...`.
- The account switcher changes local auth state but some pages keep stale data because they do not refetch on identity change.

The product direction remains: **student-owned learning data + family督促 + long-term memory coach**. These fixes should strengthen that direction without turning this release into a large new platform rewrite.

## Scope

### In Scope

- Fix Daily Review copy, default dates, checklist goals, and Agent context date handling.
- Add or rename a chat upload path so homework photos enter a “拍题批改” flow instead of the generic material flow.
- For the grading MVP, return per-question feedback: question number, recognized student answer, correct answer when available or inferable, correctness, error point, knowledge point, short explanation, and confidence/needs-review signal.
- Let the user confirm before wrong questions are saved into the error book.
- Fix local material public URLs for production while preserving local development previews.
- Make the material link action use the authenticated preview URL instead of opening stale list data directly.
- Make account switching refresh user-scoped pages and notifications.
- Update Help/Updates, current docs, tests, browser verification records, and deploy online.

### Out of Scope

- No graph database, vector database, Mem0, or full learning-map implementation in this P1 delivery.
- No WeChat entry or external push in this P1 delivery.
- No large question-bank crawling work.
- No desktop packaging/signing work.
- No migration of all historic Daily Review notes unless needed for compatibility.
- No broad visual redesign unrelated to these four flows.

## Delivery Order

1. **Material preview URL**
   - Smallest root-cause fix.
   - Unblocks reviewing uploaded real student materials online.

2. **Account switching refresh**
   - Prevents stale data while testing the remaining flows with student and parent accounts.

3. **Daily Review semantics**
   - Existing spec exists at `docs/superpowers/specs/2026-07-05-daily-review-yesterday-today-design.md`.
   - This P1 delivery should use that spec as the detailed source of truth.

4. **Photo grading MVP**
   - Largest behavior change.
   - Should be implemented after the smaller identity and preview fixes reduce test confusion.

## Architecture Design

### 1. Material Preview URL

Backend remains the source of truth for material access.

- Keep `GET /api/material/{id}/preview-url` as the authenticated preview entry.
- Add a small config-backed public upload base path, for example `PUBLIC_UPLOAD_BASE_PATH`, defaulting to `/uploads` for local development.
- Production deploy should use `/sb/uploads`.
- `material_service._build_url()` should build local `content_ref` URLs from that base path.
- COS URLs keep the existing COS behavior.
- `main.py` can continue mounting StaticFiles at `/uploads`; Nginx maps `/sb/uploads` to that backend mount in production.

Frontend:

- The preview button continues to call `preview-url`.
- The link button must also call `preview-url` and then open the returned URL.
- Avoid directly opening `record.cos_url` for local files because list data may be stale or environment-specific.

### 2. Account Switching Refresh

Account switching needs a stable identity key.

- Extend auth store with an `authVersion` or derived `accountKey` that changes on `login`, `logout`, `switchAccount`, and `setActiveChild`.
- Main layout should use the key to refresh identity-scoped state such as notifications.
- Pages that fetch user-scoped data should depend on the identity key or specific identity fields.
- At minimum, fix `MaterialsPage` because it currently loads once with `useEffect([])`.
- Prefer refetching over hard `window.location.reload()`. A hard reload may be kept only as a fallback if a page cannot be safely keyed.

### 3. Daily Review Semantics

Use the existing detailed spec:

- Default review date: yesterday.
- Default target date: today.
- UI copy: “昨日回顾 / 今日目标”.
- Today goals: checklist-style Markdown task list.
- Agent context: use server date as the only current-date anchor; do not infer current date from target date text.
- If the student has not written today’s Daily Review target, add a gentle reminder signal to Agent context.

Storage stays as confirmed notes in this delivery.

### 4. Photo Grading MVP

The product flow should be clear to a student:

1. Student clicks the chat upload button.
2. The menu clearly separates:
   - `拍题批改`
   - `上传素材`
   - optional existing `导入错题/试卷` wording if still needed for batch import.
3. Homework/problem photos enter the grading path, not the generic material path.
4. Agent or backend vision tool recognizes question content and student answers.
5. The response first grades each question, then asks for confirmation to save wrong questions.

Backend should reuse the existing exam batch and material storage pieces where reasonable:

- Do not duplicate file upload/storage logic.
- Do not trust LLM output directly for ownership or student id.
- Add a service/tool layer for grading feedback if existing `import_errors_process` is too narrow.
- Keep `import_errors_process` compatible for old flows.

Minimum grading feedback schema:

```json
{
  "questions": [
    {
      "no": "1",
      "stem": "题目内容或识别摘要",
      "student_answer": "学生作答",
      "correct_answer": "正确答案；无法确定时为空并标记需复核",
      "is_correct": false,
      "error_point": "错在哪里",
      "knowledge_tags": ["物理", "刻度尺读数"],
      "explanation": "简短讲解",
      "confidence": "high|medium|low",
      "needs_review": true
    }
  ]
}
```

Saving behavior:

- Do not auto-save all recognized questions as wrong.
- Save only after the user confirms.
- If correct answer or stem confidence is low, mark the item as needing review and explain that the student/parent should confirm.
- Wrong questions saved to the error book must still go through backend ownership checks and dedup logic.

## UX Requirements

- Labels must make the path obvious to the student. A homework photo should not look like “单词表等” material upload.
- Agent response should lead with grading, not a generic summary.
- Each graded question should be readable on mobile and desktop.
- Low-confidence items should be transparent, not hidden.
- The user should always have a manual fallback: “照片识别不清，可以手动输入题目/答案”.

## Testing Strategy

### Backend

- Material URL unit/API tests:
  - local `content_ref` returns `/uploads/...` by default.
  - when public upload base path is `/sb/uploads`, preview/list URL returns `/sb/uploads/...`.
  - preview permission boundaries remain unchanged.

- Photo grading tests:
  - parser accepts model JSON with per-question fields.
  - low-confidence or missing correct answer is represented as `needs_review`.
  - saving confirmed wrong questions reuses existing error-book service/dedup.
  - student cannot save to another student’s error book.

- Daily Review tests:
  - keep or update the existing `TestDailyReviewContext` coverage described in the Daily Review spec.

### Frontend

- Material page tests:
  - link button calls `preview-url` before opening.
  - page reloads material list when identity changes.

- Auth store/layout tests:
  - `authVersion` or `accountKey` changes on login/logout/switch account/set active child.

- Daily Review tests:
  - use the existing detailed spec acceptance criteria.

- Chat upload tests:
  - menu shows a clear `拍题批改` option.
  - uploading through that option sends the grading intent/message, not the generic material summary prompt.

### Live / Browser

- Use Codex in-app browser for:
  - local app smoke after implementation.
  - online app smoke after deploy.
- For AI/vision photo grading, run at least one live MiMo smoke with a real or controlled homework image and record:
  - tool chosen.
  - recognized questions count.
  - whether correct answers / explanation / confidence are returned.
  - elapsed time.

## Acceptance Criteria

P1 is done only when all of these are true:

- `docs/superpowers/specs/2026-07-05-p1-fixes-delivery-design.md` and an implementation plan exist.
- Material preview online opens the uploaded image/PDF or preview modal, not Visionary HTML.
- Switching from one recent account to another refreshes user-scoped data without showing stale materials/notifications.
- Daily Review shows and saves “昨日回顾 + 今日目标” with checklist goals, and Agent context no longer mislabels target dates as current dates.
- Chat upload has a clear homework grading path.
- A homework/problem photo returns per-question grading feedback with correct answer, correctness, error point, knowledge point, explanation, and confidence/needs-review status.
- Wrong questions are saved only after confirmation.
- Focused backend/frontend tests pass.
- Broader frontend verification (`typecheck`, `lint`, `build`) passes before deploy.
- Required live/real smoke is run for AI/vision behavior.
- Codex browser verifies local and public URLs.
- Help/Updates and current docs are updated.
- Deployment script runs successfully and public URL is rechecked after deployment.

## Risks and Mitigations

- **Vision may not reliably infer correct answers from a single homework photo.**
  - Mitigation: expose confidence and `needs_review`; allow manual correction; do not silently save uncertain items.

- **Production upload prefix may differ from local dev.**
  - Mitigation: use config for public upload base path; add tests for both defaults and production override.

- **Account refresh can become too broad and reset useful UI state.**
  - Mitigation: key only identity-scoped data; preserve route and non-sensitive UI where possible.

- **P1 scope can expand into long-term memory or learning-map work.**
  - Mitigation: keep Markdown material memory and learning map in the future backlog; this delivery only makes grading and current data flows reliable.

## Documentation Updates

When implementation is complete:

- Move completed P1 items out of active pending text in `docs/未实现需求清单.md`.
- Update `docs/开发进度文档.md` with test and browser verification evidence.
- Update `docs/已实现能力清单.md` with the new true boundaries.
- Update `studybuddy-client/src/data/releaseNotes.ts`.
- Keep old details archived; do not duplicate long histories in current docs.

## Review Checklist

- No hardcoded production-only URLs in components.
- No duplicated upload/storage logic.
- No frontend-only permission assumptions.
- No hidden auto-save of uncertain AI grading output.
- No broad unrelated refactor.
- No fake completion without browser and live verification evidence.
