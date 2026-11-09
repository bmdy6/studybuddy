# StudyBuddy portable source release implementation plan

**Goal:** Run the existing learning workflow from a clean checkout with user-owned configuration and synthetic data.

**Architecture:** Keep the FastAPI/MySQL backend, React client, shared service layer and Agent tool loop. Package the existing application; do not replace it with a demonstration implementation. WeChat is optional and disabled by default; local file storage uses the existing fallback.

**Tech stack:** Python 3.11+, MySQL, Node.js 20.19+, FastAPI, SQLAlchemy, React 18, Vite, an OpenAI-compatible model with tool calling.

## Constraints

- Retain plan draft confirmation, task-specific conversations, evidence-backed assessment and unfinished-plan continuation.
- Export no private Git history, accounts, student/family records, uploaded files, QR codes, private deployment configuration or unmerged functionality.
- Test only disposable local databases. Live model checks are opt-in and use fictional prompts.
- Preserve original source and unrelated work. No deployment or GitHub publication during preparation.

## Work and acceptance

- [x] Identify the complete frontend/backend dependency boundary and extract only tracked application code, public configuration and synthetic tests.
- [x] Add regression tests for absent optional WeChat configuration, disabled routes, empty internal-token rejection and explicit frontend API URLs.
- [x] Remove private API defaults; preserve user-configured API URLs in development and builds. Hide optional WeChat entry points when disabled.
- [x] Provide empty-database initialization, synthetic test setup, installation instructions and container configuration without production credentials.
- [x] Install dependencies from the exported manifests; run backend tests against a disposable MySQL instance, frontend tests/type checking/build and verify the core workflow with the evidence boundaries in `docs/verification.md`.
- [x] Perform a live model check only after identifying its provider/model and call budget. Distinguish provider-backed evidence from simulated tests.
- [x] Review exported content, third-party licensing and the final source changes independently before publication.

## Behavior matrix

| Condition | Required outcome |
| --- | --- |
| WeChat not configured | Application starts; channel endpoints reject access explicitly; primary learning flow works |
| WeChat enabled but incomplete | Configuration fails with missing field names, without credential values |
| Internal token empty | Internal endpoints reject the request even when no header is supplied |
| User supplies local API base | Both development and production build retain that URL |
| Initialization sees any existing table | Refuse to initialize; do not overwrite or migrate that database |
| LLM key absent | Return the existing explicit configuration error; do not fabricate a model answer |
| Core workflow verified | Confirmation creates one plan; task resumes the same session; assessment records evidence; carry-over includes unfinished tasks only |
