# README image provenance

All four PNGs are screenshots of the real React client backed by the real FastAPI app and a new, isolated MySQL 9.1 instance. Browser: headless Playwright Chromium, 1280 × 800. No paid model, real student data or Telegram service was used.

| Image | Page / source | Synthetic state |
| --- | --- | --- |
| overview.png | `http://127.0.0.1:15173/#/study-plans` | Learning page, prefilled unfinished plan and continue entry |
| plan-confirm.png | `http://127.0.0.1:15173/#/chat` | Main session with pending draft and confirmation card |
| task-session.png | `http://127.0.0.1:15173/#/chat` | Restored task session with fictional answer and prefilled feedback |
| resume.png | `http://127.0.0.1:15173/#/study-plans/all` | Plan list and unfinished task |

These are prefilled stage examples, not a recorded model-driven end-to-end lesson. The pending draft and existing task belong to two separately prefilled plans. `StudyPlanItemAttempt` is also prefilled; the screenshot shows saved chat history, not an independently generated assessment. No live grading, actual mastery, real-time reply or cross-day carryover is demonstrated. We do not capture a model-only state that cannot be produced offline.

Reproduction (new empty disposable database only):

1. Follow the README to install backend/frontend dependencies. Start a separate local MySQL with a new data directory and port 13317, database `readme_demo_test`, dedicated `readme_demo` account and synthetic-only password. Never use an existing database.
2. Set the synthetic environment from `capture-brief.json`, then run `PYTHONPATH=. .venv/bin/python scripts/init_db.py` in `studybuddy-backend`. This creates the real schema. Model key is blank and `LLM_BASE_URL=http://127.0.0.1:9`; optional integrations stay disabled.
3. Run the v0.3 skill from its checkout:
   `node scripts/run.mjs capture --type web-app --repo /path/to/studybuddy --work WORK --id learning --brief /path/to/studybuddy/docs/images/capture-brief.json`.
   Its setup runs `seed-demo.py` exactly once, generating the synthetic-only private browser states ignored by Git. It starts the two services in the brief, waits for readiness, opens the listed routes and stops both services afterward. Stop your separate disposable MySQL when finished.
4. Copy the four captured PNGs into this directory. Recheck against `illustrate.json`; new file hashes must match the new capture, rather than reusing this receipt.

`capture-receipt.json` preserves the actual capture receipt with only the task's absolute path replaced by `$TASK`. It records executed commands, service readiness, requested/final URLs, viewport, bytes and SHA-256. For the original run, dependency/database initialization and `seed-demo.py` ran before capture, so that receipt has no setup command; the accompanying repeatable brief includes the seed as setup. Browser-state files contain only a synthetic token but must still stay out of commits.

`baseline.json` is the pre-edit README byte snapshot. `illustrate.json` identifies the exact inserted image/caption blocks and sources. Verification strips only those blocks and compares every original byte, H2, badge and shell block. The original installation is already below the desktop fold; this image-only PR is a draft with that hard failure disclosed. README preview screenshots are kept outside the repository.
