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
                    prompt TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    aspect_ratio TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    provider_task_id TEXT,
                    output_video_path TEXT,
                    request_json_path TEXT,
                    result_json_path TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
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
                    prompt,
                    provider,
                    duration_seconds,
                    aspect_ratio,
                    status,
                    progress,
                    provider_task_id,
                    output_video_path,
                    request_json_path,
                    result_json_path,
                    retry_count,
                    error_code,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                "SELECT COUNT(*) AS total FROM tasks WHERE batch_id = ? AND status = ?",
                (batch_id, TaskStatus.RUNNING.value),
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
                SET status = ?, progress = 10, error_code = NULL, error_message = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (TaskStatus.RUNNING.value, now, row["id"], TaskStatus.QUEUED.value),
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
                WHERE status = ?
                """,
                (TaskStatus.QUEUED.value, now, TaskStatus.RUNNING.value),
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
                    error_message = NULL, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.SUCCEEDED.value,
                    provider_task_id,
                    str(output_video_path),
                    str(request_json_path),
                    str(result_json_path),
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
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, progress = 100, request_json_path = COALESCE(?, request_json_path),
                    result_json_path = COALESCE(?, result_json_path), error_code = ?,
                    error_message = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.FAILED.value,
                    str(request_json_path) if request_json_path else None,
                    str(result_json_path) if result_json_path else None,
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
                    provider_task_id = NULL, output_video_path = NULL, request_json_path = NULL,
                    result_json_path = NULL, error_code = NULL, error_message = NULL,
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
        if any(status in statuses for status in {TaskStatus.QUEUED, TaskStatus.RUNNING}):
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
            task.prompt,
            task.provider,
            task.duration_seconds,
            task.aspect_ratio,
            task.status.value,
            task.progress,
            task.provider_task_id,
            task.output_video_path,
            task.request_json_path,
            task.result_json_path,
            task.retry_count,
            task.error_code,
            task.error_message,
            task.created_at,
            task.updated_at,
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
            prompt=row["prompt"],
            provider=row["provider"],
            duration_seconds=row["duration_seconds"],
            aspect_ratio=row["aspect_ratio"],
            status=TaskStatus(row["status"]),
            progress=row["progress"],
            provider_task_id=row["provider_task_id"],
            output_video_path=row["output_video_path"],
            request_json_path=row["request_json_path"],
            result_json_path=row["result_json_path"],
            retry_count=row["retry_count"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
