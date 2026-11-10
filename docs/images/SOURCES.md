# README image sources

Four screenshots from the real React → FastAPI → isolated MySQL 9.1 application, using hand-authored synthetic plans, dialogue and feedback; no model calls. The draft and task are separate fixture plans.

| Image | Route | Viewport | SHA-256 |
| --- | --- | --- | --- |
| overview.png | http://127.0.0.1:15173/#/study-plans | 1280×800 | `61754d940df66c967c33502eb531df5c2dca475599070062804b9b33297443f7` |
| plan-confirm.png | http://127.0.0.1:15173/#/chat | 1280×800 | `b6a099fa53250a825a5d51c00ca9f95a6b8eeb42ee48445dfb0d2edfd4c815fa` |
| task-session.png | http://127.0.0.1:15173/#/chat | 1120×650 | `22c69ed3647662a404c754ffb14c545d0de45c23e3d4c9cacce6f55573350e89` |
| resume.png | http://127.0.0.1:15173/#/study-plans/all | 1280×800 | `aef5f1ead104a5d3e983ff71315c57d04de00238a7fb16eb9e0dfd034b85c9b9` |

Reproduce in a new disposable local database named `readme_demo_test`: install dependencies and initialize with `PYTHONPATH=. .venv/bin/python scripts/init_db.py`, then run `PYTHONPATH=. .venv/bin/python ../docs/images/seed-demo.py` from studybuddy-backend. The script creates only fictional records and ignored browser states. Set the database host to 127.0.0.1, a dedicated local port/account, blank LLM_API_KEY, LLM_BASE_URL=http://127.0.0.1:9 and WECHAT_ENABLED=false. Start FastAPI on 18011 and Vite on 15173 with VITE_API_BASE=http://127.0.0.1:18011; load the routes above with the script's plan/task storage states in headless Chromium.

Capture command: `node /path/to/skill/scripts/run.mjs capture --type web-app --repo . --work WORK --id learning --brief WORK/brief.json`. The brief supplies setup, service commands/readiness, routes, viewports and storage-state paths. Keep that brief, capture receipt and README previews outside the repository; stop owned services after capture.

The compact illustrate.json records baseline commit/blob references, hashes and insertion fields. Verify uses git show to compare original README bytes after removing declared blocks. Baseline installation was already below the desktop fold; report it as a warning.
