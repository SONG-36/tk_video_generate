# Feature Checklists

Read only the sections relevant to the task.

## API feature

- Define Pydantic request and response schemas.
- Keep the route thin and use dependency injection.
- Call a service rather than a repository/provider directly.
- Return the established response/error shape unless endpoint compatibility requires otherwise.
- Add success, validation, and important failure tests.
- Update API documentation or README when consumers need new setup or behavior information.

## Database feature

- Update typed SQLAlchemy models and relationships.
- Use explicit nullable, length, index, uniqueness, and foreign-key behavior.
- Use `Decimal`/`Numeric`, never float, for money.
- Generate a focused Alembic revision with working upgrade and downgrade.
- Inspect offline SQL and test model metadata/mappers.
- Avoid destructive or irreversible migrations unless explicitly authorized.

## Repository and service feature

- Put reusable queries in repositories.
- Define transaction ownership clearly; do not commit unpredictably inside helpers.
- Put state transitions, validation, orchestration, and provider selection in services.
- Test service behavior with mock repositories/providers.
- Preserve idempotency for retryable task operations where practical.

## Provider integration

- Implement the existing abstract image or video Provider interface.
- Keep vendor request/response translation inside the adapter.
- Use `httpx` or an explicitly approved SDK with timeouts.
- Read endpoint, model, and secret configuration from settings.
- Normalize vendor errors into stable application errors.
- Record provider/model/task IDs and usage data without logging secrets.
- Mock all paid/network behavior in ordinary tests.

## Celery task

- Accept stable serializable identifiers, normally `task_id`.
- Load state and call a service; keep task code thin.
- Route image and video tasks to their existing queues.
- Make retry behavior explicit and safe.
- Log identifiers and state transitions without prompt contents or credentials.
- Test in eager mode without Redis.

## Frontend feature

- Define shared TypeScript request/response and form types.
- Put HTTP calls in `src/api`.
- Put reusable validation in `src/utils`.
- Split reusable UI into `src/components`; keep view orchestration in `src/views`.
- Supply safe defaults and preserve the ten-card batch limit.
- Show field/card errors and prevent partial invalid submission.
- Keep keyboard labels, loading state, disabled state, empty state, and failure feedback usable.
- Run type-check, ESLint, and Vite build.

## Upload or media feature

- Validate extension, MIME type, file count, and size on frontend and backend.
- Never trust the client filename as a storage path.
- Generate safe server-side names.
- Use `FileStorageService` and persist only a relative path.
- Clean partial files when a database operation fails.
- Avoid exposing arbitrary local filesystem paths in responses.

## Configuration change

- Add a typed setting with a safe development default only when appropriate.
- Add a placeholder to `.env.example`.
- Update Docker Compose or start scripts when they consume the value.
- Add or update a configuration loading test.
- Do not place a real credential in examples or tests.

## Completion

- Run the smallest relevant checks plus regression tests for touched layers.
- Exercise the changed endpoint or UI flow when feasible.
- Confirm no real paid provider was called unintentionally.
- State which infrastructure-dependent checks were not run.

