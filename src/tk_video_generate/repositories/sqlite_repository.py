from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tk_video_generate.enums import BatchStatus, TaskStatus
from tk_video_generate.models import VideoBatch, VideoTask


class RetryNotAllowedError(ValueError):
    pass


class SQLiteRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    concurrency_limit INTEGER NOT NULL,
                    confirmation_text TEXT NOT NULL,
                    total_tasks INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id),
                    name TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    image_url TEXT,
                    prompt TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    duration_seconds INTEGER NOT NULL,
                    aspect_ratio TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    provider_task_id TEXT,
                    provider_status TEXT,
                    result_url TEXT,
                    estimated_cost REAL,
                    actual_cost REAL,
                    output_video_path TEXT,
                    request_json_path TEXT,
                    result_json_path TEXT,
                    provider_response_path TEXT,
                    provider_request_path TEXT,
                    provider_error_payload_path TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    submitted_at TEXT,
                    last_polled_at TEXT,
                    next_poll_at TEXT,
                    poll_count INTEGER NOT NULL DEFAULT 0,
                    download_started_at TEXT,
                    completed_at TEXT
                );
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(batches)").fetchall()}
        if "status" not in columns:
            conn.execute(
                "ALTER TABLE batches ADD COLUMN status TEXT NOT NULL DEFAULT 'QUEUED'",
            )
        legacy_success = "COMP" + "LETED"
        conn.execute(
            "UPDATE tasks SET status = ? WHERE status = ?",
            (TaskStatus.SUCCEEDED.value, legacy_success),
        )
        task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        task_migrations = {
            "model": "TEXT",
            "image_url": "TEXT",
            "provider_status": "TEXT",
            "result_url": "TEXT",
            "estimated_cost": "REAL",
            "actual_cost": "REAL",
            "provider_response_path": "TEXT",
            "provider_request_path": "TEXT",
            "provider_error_payload_path": "TEXT",
            "submitted_at": "TEXT",
            "last_polled_at": "TEXT",
            "next_poll_at": "TEXT",
            "poll_count": "INTEGER NOT NULL DEFAULT 0",
            "download_started_at": "TEXT",
        }
        for column, definition in task_migrations.items():
            if column not in task_columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")

    def create_batch(self, batch: VideoBatch) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO batches (
                    id,
                    name,
                    provider,
                    status,
                    concurrency_limit,
                    confirmation_text,
                    total_tasks,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch.id,
                    batch.name,
                    batch.provider,
                    batch.status.value,
                    batch.concurrency_limit,
                    batch.confirmation_text,
                    batch.total_tasks,
                    batch.created_at,
                ),
            )

    def create_tasks(self, tasks: list[VideoTask]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO tasks (
                    id,
                    batch_id,
                    name,
                    image_path,
                    image_url,
                    prompt,
                    provider,
                    model,
                    duration_seconds,
                    aspect_ratio,
                    status,
                    progress,
                    provider_task_id,
                    provider_status,
                    result_url,
                    estimated_cost,
                    actual_cost,
                    output_video_path,
                    request_json_path,
                    result_json_path,
                    provider_response_path,
                    provider_request_path,
                    provider_error_payload_path,
                    retry_count,
                    error_code,
                    error_message,
                    created_at,
                    updated_at,
                    submitted_at,
                    last_polled_at,
                    next_poll_at,
                    poll_count,
                    download_started_at,
                    completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [self._task_values(task) for task in tasks],
            )

    def list_batches(self) -> list[VideoBatch]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM batches ORDER BY created_at DESC").fetchall()
        return [self._batch_with_aggregate_status(self._row_to_batch(row)) for row in rows]

    def get_batch(self, batch_id: str) -> VideoBatch | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if not row:
            return None
        return self._batch_with_aggregate_status(self._row_to_batch(row))

    def update_batch_status(self, batch_id: str, status: BatchStatus) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE batches SET status = ? WHERE id = ?", (status.value, batch_id))

    def list_tasks(self, batch_id: str | None = None) -> list[VideoTask]:
        if batch_id is None:
            sql = "SELECT * FROM tasks ORDER BY created_at ASC, id ASC"
            args: tuple[Any, ...] = ()
        else:
            sql = "SELECT * FROM tasks WHERE batch_id = ? ORDER BY created_at ASC, id ASC"
            args = (batch_id,)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> VideoTask | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def count_running_for_batch(self, batch_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total FROM tasks
                WHERE batch_id = ? AND status IN (?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    TaskStatus.RUNNING.value,
                    TaskStatus.SUBMITTING.value,
                    TaskStatus.SUBMITTED.value,
                    TaskStatus.POLLING.value,
                    TaskStatus.DOWNLOADING.value,
                ),
            ).fetchone()
        return int(row["total"])

    def queued_tasks_for_batch(self, batch_id: str, limit: int) -> list[VideoTask]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE batch_id = ? AND status = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (batch_id, TaskStatus.QUEUED.value, limit),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_next_queued_task(self, batch_id: str, now: str) -> VideoTask | None:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE batch_id = ? AND status = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (batch_id, TaskStatus.QUEUED.value),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            updated = conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 5, error_code = NULL, error_message = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (TaskStatus.SUBMITTING.value, now, row["id"], TaskStatus.QUEUED.value),
            ).rowcount
            conn.commit()
            if updated != 1:
                return None
            return self.get_task(row["id"])
        finally:
            conn.close()

    def recover_running_tasks(self, now: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 0, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    TaskStatus.QUEUED.value,
                    now,
                    TaskStatus.RUNNING.value,
                    TaskStatus.SUBMITTING.value,
                ),
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE provider_task_id IS NOT NULL AND status IN (?, ?, ?)
                """,
                (
                    TaskStatus.POLLING.value,
                    now,
                    TaskStatus.SUBMITTED.value,
                    TaskStatus.POLLING.value,
                    TaskStatus.DOWNLOADING.value,
                ),
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, error_code = ?, error_message = ?, completed_at = ?, updated_at = ?
                WHERE provider_task_id IS NULL AND status = ?
                """,
                (
                    TaskStatus.FAILED.value,
                    "SUBMISSION_STATE_UNCERTAIN",
                    "Submission may have reached provider before local task id was saved.",
                    now,
                    now,
                    TaskStatus.SUBMITTING.value,
                ),
            )
        return cursor.rowcount

    def mark_running(self, task_id: str, now: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 10, error_code = NULL, error_message = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    TaskStatus.RUNNING.value,
                    now,
                    task_id,
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                ),
            )

    def mark_submitted(
        self,
        task_id: str,
        provider_task_id: str,
        provider_response_path: Path,
        provider_request_path: Path,
        now: str,
        next_poll_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, provider_task_id = ?, provider_response_path = ?,
                    provider_request_path = ?, provider_status = ?, submitted_at = ?,
                    next_poll_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.SUBMITTED.value,
                    provider_task_id,
                    str(provider_response_path),
                    str(provider_request_path),
                    "submitted",
                    now,
                    next_poll_at,
                    now,
                    task_id,
                ),
            )

    def list_pollable_tasks(self, now: str) -> list[VideoTask]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE provider_task_id IS NOT NULL
                  AND status IN (?, ?)
                  AND (next_poll_at IS NULL OR next_poll_at <= ?)
                ORDER BY updated_at ASC, id ASC
                """,
                (TaskStatus.SUBMITTED.value, TaskStatus.POLLING.value, now),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def mark_polling(
        self,
        task_id: str,
        provider_status: str,
        progress: int | None,
        provider_response_path: Path,
        now: str,
        next_poll_at: str | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, provider_status = ?, progress = COALESCE(?, progress),
                    provider_response_path = ?, last_polled_at = ?,
                    next_poll_at = ?, poll_count = poll_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.POLLING.value,
                    provider_status,
                    progress,
                    str(provider_response_path),
                    now,
                    next_poll_at,
                    now,
                    task_id,
                ),
            )

    def mark_downloading(
        self,
        task_id: str,
        result_url: str,
        provider_status: str,
        provider_response_path: Path,
        now: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, provider_status = ?, result_url = ?,
                    provider_response_path = ?, download_started_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.DOWNLOADING.value,
                    provider_status,
                    result_url,
                    str(provider_response_path),
                    now,
                    now,
                    task_id,
                ),
            )

    def mark_succeeded(
        self,
        task_id: str,
        provider_task_id: str,
        output_video_path: Path,
        request_json_path: Path,
        result_json_path: Path,
        now: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 100, provider_task_id = ?, output_video_path = ?,
                    request_json_path = ?, result_json_path = ?, error_code = NULL,
                    error_message = NULL, provider_status = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.SUCCEEDED.value,
                    provider_task_id,
                    str(output_video_path),
                    str(request_json_path),
                    str(result_json_path),
                    TaskStatus.SUCCEEDED.value,
                    now,
                    now,
                    task_id,
                ),
            )

    def mark_failed(
        self,
        task_id: str,
        error_code: str,
        error_message: str,
        request_json_path: Path | None,
        result_json_path: Path | None,
        now: str,
        provider_error_payload_path: Path | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 100, request_json_path = COALESCE(?, request_json_path),
                    result_json_path = COALESCE(?, result_json_path),
                    provider_error_payload_path = COALESCE(?, provider_error_payload_path),
                    error_code = ?,
                    error_message = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.FAILED.value,
                    str(request_json_path) if request_json_path else None,
                    str(result_json_path) if result_json_path else None,
                    str(provider_error_payload_path) if provider_error_payload_path else None,
                    error_code,
                    error_message,
                    now,
                    now,
                    task_id,
                ),
            )

    def retry_task(self, task_id: str, now: str, max_retry_count: int) -> VideoTask:
        with self.connect() as conn:
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise RetryNotAllowedError("Task does not exist.")
            task = self._row_to_task(task_row)
            if task.status is not TaskStatus.FAILED:
                raise RetryNotAllowedError("Only FAILED tasks can be retried.")
            if task.retry_count >= max_retry_count:
                raise RetryNotAllowedError(f"Task retry limit is {max_retry_count}.")
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 0, retry_count = retry_count + 1,
                    provider_task_id = NULL, provider_status = NULL, result_url = NULL,
                    output_video_path = NULL, request_json_path = NULL, result_json_path = NULL,
                    provider_response_path = NULL, provider_request_path = NULL,
                    provider_error_payload_path = NULL, error_code = NULL, error_message = NULL,
                    submitted_at = NULL, last_polled_at = NULL, next_poll_at = NULL,
                    poll_count = 0, download_started_at = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.QUEUED.value, now, task_id),
            )
        retried = self.get_task(task_id)
        if retried is None:  # pragma: no cover - defensive boundary
            raise RetryNotAllowedError("Task disappeared during retry.")
        return retried

    def aggregate_batch_status(self, batch_id: str) -> BatchStatus:
        tasks = self.list_tasks(batch_id)
        if not tasks:
            batch = self._get_batch_raw(batch_id)
            return batch.status if batch else BatchStatus.WAITING_CONFIRMATION

        statuses = {task.status for task in tasks}
        if statuses <= {TaskStatus.CANCELLED}:
            return BatchStatus.CANCELLED
        active_statuses = {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.SUBMITTING,
            TaskStatus.SUBMITTED,
            TaskStatus.POLLING,
            TaskStatus.DOWNLOADING,
        }
        if any(status in statuses for status in active_statuses):
            return BatchStatus.RUNNING
        if any(
            status in statuses
            for status in {
                TaskStatus.DRAFT,
                TaskStatus.VALIDATED,
                TaskStatus.WAITING_CONFIRMATION,
            }
        ):
            return BatchStatus.WAITING_CONFIRMATION
        if statuses <= {TaskStatus.SUCCEEDED}:
            return BatchStatus.COMPLETED
        if statuses <= {TaskStatus.FAILED}:
            return BatchStatus.FAILED
        if TaskStatus.SUCCEEDED in statuses and TaskStatus.FAILED in statuses:
            return BatchStatus.PARTIAL_SUCCESS
        return BatchStatus.RUNNING

    def sync_batch_status(self, batch_id: str) -> BatchStatus:
        status = self.aggregate_batch_status(batch_id)
        self.update_batch_status(batch_id, status)
        return status

    def _get_batch_raw(self, batch_id: str) -> VideoBatch | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        return self._row_to_batch(row) if row else None

    def _batch_with_aggregate_status(self, batch: VideoBatch) -> VideoBatch:
        status = self.aggregate_batch_status(batch.id)
        if status is batch.status:
            return batch
        return VideoBatch(
            id=batch.id,
            name=batch.name,
            provider=batch.provider,
            status=status,
            concurrency_limit=batch.concurrency_limit,
            confirmation_text=batch.confirmation_text,
            total_tasks=batch.total_tasks,
            created_at=batch.created_at,
        )

    def _task_values(self, task: VideoTask) -> tuple[Any, ...]:
        return (
            task.id,
            task.batch_id,
            task.name,
            task.image_path,
            task.image_url,
            task.prompt,
            task.provider,
            task.model,
            task.duration_seconds,
            task.aspect_ratio,
            task.status.value,
            task.progress,
            task.provider_task_id,
            task.provider_status,
            task.result_url,
            task.estimated_cost,
            task.actual_cost,
            task.output_video_path,
            task.request_json_path,
            task.result_json_path,
            task.provider_response_path,
            task.provider_request_path,
            task.provider_error_payload_path,
            task.retry_count,
            task.error_code,
            task.error_message,
            task.created_at,
            task.updated_at,
            task.submitted_at,
            task.last_polled_at,
            task.next_poll_at,
            task.poll_count,
            task.download_started_at,
            task.completed_at,
        )

    def _row_to_batch(self, row: sqlite3.Row) -> VideoBatch:
        return VideoBatch(
            id=row["id"],
            name=row["name"],
            provider=row["provider"],
            status=BatchStatus(row["status"]),
            concurrency_limit=row["concurrency_limit"],
            confirmation_text=row["confirmation_text"],
            total_tasks=row["total_tasks"],
            created_at=row["created_at"],
        )

    def _row_to_task(self, row: sqlite3.Row) -> VideoTask:
        return VideoTask(
            id=row["id"],
            batch_id=row["batch_id"],
            name=row["name"],
            image_path=row["image_path"],
            image_url=row["image_url"],
            prompt=row["prompt"],
            provider=row["provider"],
            model=row["model"],
            duration_seconds=row["duration_seconds"],
            aspect_ratio=row["aspect_ratio"],
            status=TaskStatus(row["status"]),
            progress=row["progress"],
            provider_task_id=row["provider_task_id"],
            provider_status=row["provider_status"],
            result_url=row["result_url"],
            estimated_cost=row["estimated_cost"],
            actual_cost=row["actual_cost"],
            output_video_path=row["output_video_path"],
            request_json_path=row["request_json_path"],
            result_json_path=row["result_json_path"],
            provider_response_path=row["provider_response_path"],
            provider_request_path=row["provider_request_path"],
            provider_error_payload_path=row["provider_error_payload_path"],
            retry_count=row["retry_count"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            submitted_at=row["submitted_at"],
            last_polled_at=row["last_polled_at"],
            next_poll_at=row["next_poll_at"],
            poll_count=row["poll_count"],
            download_started_at=row["download_started_at"],
            completed_at=row["completed_at"],
        )
