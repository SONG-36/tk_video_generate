# Architecture Contract

## Product boundary

TikTok Operations Studio is a company-internal, single-machine tool for configuring and running
batch image and video generation. It is a frontend/backend separated modular monolith, not a
microservice system.

Current menu surfaces:

- image generation;
- video generation.

Do not add authentication or history screens by default. Treat real image/video vendor integration
as explicit future work rather than an implied dependency of ordinary feature tasks.

## Fixed technology stack

Frontend:

- Vue 3 and TypeScript;
- Vite;
- Element Plus;
- Axios;
- Pinia;
- Vue Router.

Backend:

- Python 3.12;
- FastAPI and Pydantic;
- SQLAlchemy 2 and Alembic;
- PyMySQL;
- Uvicorn;
- httpx and Pillow.

Infrastructure:

- Celery with Redis;
- MySQL 8;
- local filesystem storage;
- Docker Compose for MySQL and Redis;
- pytest and FastAPI TestClient.

Respect versions already pinned in `frontend/package.json` and `backend/requirements.txt`. Upgrade
only when the feature requires it, and confirm local runtime compatibility first.

## Repository layout

```text
tiktok-operations-studio/
├─ frontend/src/
│  ├─ api/
│  ├─ components/
│  ├─ layouts/
│  ├─ router/
│  ├─ stores/
│  ├─ types/
│  ├─ utils/
│  └─ views/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  ├─ repositories/
│  │  ├─ services/
│  │  ├─ providers/image/
│  │  ├─ providers/video/
│  │  ├─ media/
│  │  └─ tasks/
│  ├─ alembic/
│  └─ tests/
├─ storage/
│  ├─ uploads/{image,video}/
│  ├─ outputs/{image,video}/
│  └─ temp/
├─ scripts/
├─ docker-compose.yml
├─ .env.example
└─ README.md
```

## Backend responsibilities

- `api`: transport concerns, dependency injection, request/response schemas.
- `schemas`: validated API and service boundary data.
- `services`: use-case orchestration and business rules.
- `repositories`: persistence queries and writes.
- `providers`: vendor-neutral interfaces and vendor-specific adapters.
- `tasks`: thin Celery entry points that invoke services.
- `models`: SQLAlchemy persistence definitions.
- `core`: settings, database, logging, exceptions.
- `media`: low-level media inspection/transformation helpers.

Routes and Celery tasks must not accumulate business logic. Services must not depend on FastAPI
request objects or concrete vendor SDKs.

## Existing data model

`generation_batch`:

- types: `IMAGE`, `VIDEO`;
- statuses: `PENDING`, `RUNNING`, `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`;
- counters: total, success, failed.

`generation_task`:

- types: `IMAGE`, `VIDEO`;
- statuses: `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`;
- belongs to a batch;
- records prompt, provider/model identity, provider task ID, errors, and timing.

`provider_usage`:

- belongs one-to-one to a task;
- records token and billing measurements;
- sources: `PROVIDER`, `LOCAL_CALCULATION`, `UNKNOWN`;
- monetary fields use fixed-precision decimal types;
- `pricing_snapshot` preserves the pricing inputs used for later audit.

Preserve enum values once persisted. Add transitions deliberately and test them.

## Configuration contract

Existing keys:

```text
APP_ENV
APP_HOST
APP_PORT
MYSQL_HOST
MYSQL_PORT
MYSQL_DATABASE
MYSQL_USER
MYSQL_PASSWORD
REDIS_HOST
REDIS_PORT
REDIS_DB
STORAGE_ROOT
IMAGE_WORKER_CONCURRENCY
VIDEO_WORKER_CONCURRENCY
```

Never commit `.env`, real passwords, tokens, API keys, or machine-specific absolute paths.

## Frontend product rules

All task pages begin with one card and allow at most ten cards. A failed card blocks the whole
batch, shows a visible error, and scrolls the first invalid card into view.

Image task defaults:

- ratio `9:16`; options `9:16`, `3:4`, `1:1`;
- count `1`; options `1`, `2`, `4`.

Video task defaults:

- reference mode `参考生成`; alternative `首帧图`;
- resolution `720P`; alternative `480P`;
- ratio `9:16`; alternative `16:9`;
- duration mode `固定时长`; alternative `智能时长`;
- fixed duration `5`; options `5`, `10`, `15` seconds;
- sound off;
- exactly one generated video per task.

Hide or disable fixed duration in smart-duration mode. First-frame mode permits only one reference
image.

## Storage contract

Persist POSIX-style paths relative to `STORAGE_ROOT`, such as
`outputs/image/123/result.png`. Resolve and validate paths through `FileStorageService`. Do not
store `C:\...`, drive letters, UNC paths, or `..` traversal.

