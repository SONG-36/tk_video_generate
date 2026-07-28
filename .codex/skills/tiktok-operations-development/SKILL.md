---
name: tiktok-operations-development
description: Develop, modify, debug, review, or test feature code in the TikTok Operations Studio project while preserving its Vue 3 + FastAPI modular-monolith architecture. Use for frontend task forms, FastAPI APIs, SQLAlchemy models and Alembic migrations, repositories, services, image/video providers, Celery tasks, local media storage, MySQL/Redis configuration, tests, and project documentation inside this repository.
---

# TikTok Operations Studio Development

Implement production-quality feature changes without drifting from the project's architecture,
technology stack, or current product scope.

## Start every task

1. Locate the project root by finding both `frontend/package.json` and
   `backend/app/main.py`. Do not assume the shell starts in the root.
2. Read [references/architecture.md](references/architecture.md) before changing code.
3. Read [references/feature-checklists.md](references/feature-checklists.md) for the layers
   affected by the request.
4. Inspect existing files and working-tree changes. Preserve user changes and established
   patterns.
5. Restate any material assumption only when the request leaves a product decision open.

## Plan the change by layer

Keep the dependency direction:

```text
API / Celery task -> Service -> Provider abstraction or Repository -> Database / external system
```

For frontend work, keep API clients, types, validation, reusable components, and views separate.
For cross-layer features, define the request/response contract first, then implement the backend
and frontend against the same contract.

Change only the layers needed by the feature. Do not introduce a new framework, microservice,
authentication system, history page, or infrastructure service unless the user explicitly expands
the scope.

## Implement safely

- Use Python 3.12 type annotations and SQLAlchemy 2 typed mappings.
- Put orchestration and business rules in services, not API routes or Celery tasks.
- Depend on image/video Provider interfaces rather than concrete vendors.
- Create an Alembic revision for every persistent schema change. Never replace migrations with
  application-startup `create_all`.
- Represent prices and monetary quantities with `Decimal` and `DECIMAL(20,8)` or stricter
  precision. Never use `float`.
- Store only paths relative to `STORAGE_ROOT`; reject absolute paths and traversal.
- Read credentials, endpoints, concurrency, and environment-specific values from settings.
  Update `.env.example` whenever adding configuration.
- Validate untrusted input on the backend even when equivalent frontend validation exists.
- Preserve the existing upload constraints unless the user changes the product rule: JPG/JPEG/PNG,
  matching extension and MIME type, 10 MB per file, five references maximum, and one image in
  first-frame mode.
- Do not call OpenAI, Volcengine, or another paid provider unless the task explicitly requests a
  real integration. Keep mock behavior deterministic in tests.

## Validate proportionally

Run the bundled checker from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\.codex\skills\tiktok-operations-development\scripts\check-project.ps1
```

Use `-Area frontend` or `-Area backend` for isolated work. The script skips missing dependency
environments and reports them; never claim skipped checks passed.

For database changes, also inspect the migration and run:

```powershell
Set-Location backend
.\.venv\Scripts\alembic.exe upgrade head --sql
```

For API changes, exercise the affected endpoint with `TestClient` or a running local server.
For UI behavior changes, type-check and build at minimum; use browser interaction only when the
user requests visual or interaction QA.

Fix failures caused by the change. Report unrelated pre-existing failures separately.

## Finish the task

Summarize:

- behavior delivered;
- important files or migrations changed;
- checks actually run and their outcomes;
- external services not exercised;
- any intentionally deferred work.

Do not report generated dependency folders, caches, or build output as source changes.

