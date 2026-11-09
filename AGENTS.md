# StudyBuddy development

- Keep the existing router → service → model boundaries. HTTP and Agent tools share the same authorization and transaction services.
- Preserve draft confirmation, evidence requirements, task-session ownership and idempotency. Do not describe AI judgments as proof of mastery.
- Work in an isolated branch/workspace. Never copy credentials, user records, uploads or private deployment history into this repository.
- Use disposable synthetic local databases for tests. Read `docs/testing.md` before executing tests; do not reuse a personal or production database.
- Configure models explicitly. Live calls require a bounded call budget and must be reported separately from mocked tests.
- Run relevant backend tests plus frontend tests, lint, type checking and build for affected changes. Check the real browser flow when changing visible behavior.
- Optional integrations remain disabled unless explicitly configured. No deployment or data migration is implied by a code change.
