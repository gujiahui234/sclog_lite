"""Asynchronous, batched MySQL persistence with failure isolation."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import BatchConfig, MySQLConfig, PoolConfig
from .pool import MySQLConnectionPool
from .records import DatabaseRecord

_INSERT_COLUMNS = (
    "logged_at_utc",
    "level_name",
    "level_no",
    "message",
    "logger_name",
    "module",
    "function_name",
    "file_name",
    "file_path",
    "line_no",
    "process_id",
    "process_name",
    "thread_id",
    "thread_name",
    "elapsed_ms",
    "extra_json",
    "exception_text",
)


@dataclass(frozen=True, slots=True)
class WriterStats:
    """Immutable snapshot of asynchronous writer counters."""

    submitted: int
    written: int
    failed: int
    dead_lettered: int
    dropped: int
    batches: int
    retries: int
    queue_size: int


class AsyncMySQLWriter:
    """Persist log records in a background thread using batch inserts."""

    def __init__(
        self,
        mysql: MySQLConfig,
        pool_config: PoolConfig,
        batch: BatchConfig,
        *,
        pool: Any | None = None,
    ) -> None:
        """Create and start a background writer.

        Args:
            mysql: MySQL connection and table settings.
            pool_config: Connection-pool settings.
            batch: Queue, batching, retry, and dead-letter settings.
            pool: Optional pool-compatible object used by tests.
        """

        self._mysql = mysql
        self._batch = batch
        self._pool = pool or MySQLConnectionPool(mysql, pool_config)
        self._queue: queue.Queue[DatabaseRecord] = queue.Queue(maxsize=batch.queue_size)
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._pool_closed = threading.Event()
        self._table_ready = not mysql.create_table
        self._dead_letter_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._submitted = 0
        self._written = 0
        self._failed = 0
        self._dead_lettered = 0
        self._dropped = 0
        self._batches = 0
        self._retries = 0
        self._thread = threading.Thread(
            target=self._run,
            name="sclog-lite-mysql-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(self, record: DatabaseRecord) -> bool:
        """Submit one record without waiting for MySQL.

        Args:
            record: Detached Loguru record.

        Returns:
            ``True`` if queued, otherwise ``False``.
        """

        self._increment("_submitted")
        if self._closed.is_set():
            self._isolate([record], reason="writer_closed", error=None)
            return False
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            if self._batch.overflow_policy == "dead_letter":
                self._isolate([record], reason="queue_full", error=None)
            else:
                self._increment("_dropped")
            return False
        return True

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until all currently queued records have been handled.

        Args:
            timeout: Maximum wait in seconds. ``None`` uses ``shutdown_timeout``.

        Returns:
            ``True`` when the queue drained before the deadline.
        """

        wait_for = self._batch.shutdown_timeout if timeout is None else timeout
        deadline = time.monotonic() + max(0.0, wait_for)
        while True:
            with self._queue.all_tasks_done:
                if self._queue.unfinished_tasks == 0:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def close(self, timeout: float | None = None) -> bool:
        """Stop accepting records, flush the queue, and close the pool.

        Args:
            timeout: Maximum wait for the worker.

        Returns:
            ``True`` when the worker stopped cleanly.
        """

        wait_for = self._batch.shutdown_timeout if timeout is None else timeout
        with self._close_lock:
            self._closed.set()
            self._stop.set()
            if threading.current_thread() is self._thread:
                return False
            self._thread.join(timeout=max(0.0, wait_for))
            stopped = not self._thread.is_alive()
            if stopped:
                self._close_pool_once()
            else:
                self._internal_error(
                    f"writer did not stop within {max(0.0, wait_for):.3f}s; "
                    "remaining records stay isolated from application logging"
                )
            return stopped

    def stats(self) -> WriterStats:
        """Return a thread-safe metrics snapshot."""

        with self._stats_lock:
            return WriterStats(
                submitted=self._submitted,
                written=self._written,
                failed=self._failed,
                dead_lettered=self._dead_lettered,
                dropped=self._dropped,
                batches=self._batches,
                retries=self._retries,
                queue_size=self._queue.qsize(),
            )

    def _run(self) -> None:
        try:
            try:
                self._pool.warmup()
            except Exception as exc:
                self._internal_error(f"MySQL pool warmup failed: {exc}")

            while not self._stop.is_set() or not self._queue.empty():
                try:
                    first = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                records = self._collect_batch(first)
                try:
                    self._write_with_retries(records)
                except Exception as exc:  # pragma: no cover - final safety boundary
                    self._internal_error(f"unexpected writer failure: {exc}")
                    self._isolate(records, reason="unexpected_writer_failure", error=exc)
                finally:
                    for _ in records:
                        self._queue.task_done()
        finally:
            self._close_pool_once()

    def _collect_batch(self, first: DatabaseRecord) -> list[DatabaseRecord]:
        records = [first]
        deadline = time.monotonic() + self._batch.flush_interval
        while len(records) < self._batch.batch_size:
            timeout = (
                0.0
                if self._stop.is_set()
                else max(0.0, deadline - time.monotonic())
            )
            if timeout == 0.0 and not self._stop.is_set():
                break
            try:
                if timeout == 0.0:
                    records.append(self._queue.get_nowait())
                else:
                    records.append(self._queue.get(timeout=timeout))
            except queue.Empty:
                break
        return records

    def _write_with_retries(self, records: list[DatabaseRecord]) -> None:
        last_error: Exception | None = None
        for attempt in range(self._batch.max_retries + 1):
            try:
                self._insert_batch(records)
            except Exception as exc:
                last_error = exc
                if attempt >= self._batch.max_retries:
                    break
                self._increment("_retries")
                delay = min(
                    self._batch.retry_backoff * (2**attempt),
                    self._batch.retry_backoff_max,
                )
                if delay > 0:
                    self._stop.wait(delay)
            else:
                self._add_written(len(records))
                return

        self._add_failed(len(records))
        self._isolate(records, reason="mysql_batch_failed", error=last_error)
        self._internal_error(
            f"MySQL batch failed after {self._batch.max_retries + 1} attempt(s): "
            f"{last_error}"
        )

    def _insert_batch(self, records: list[DatabaseRecord]) -> None:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                if not self._table_ready:
                    cursor.execute(self._create_table_sql())
                cursor.executemany(
                    self._insert_sql(),
                    [record.as_mysql_parameters() for record in records],
                )
            connection.commit()
        self._table_ready = True

    def _create_table_sql(self) -> str:
        table = self._mysql.table
        return f"""
CREATE TABLE IF NOT EXISTS `{table}` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `logged_at_utc` DATETIME(6) NOT NULL,
    `level_name` VARCHAR(32) NOT NULL,
    `level_no` INT NOT NULL,
    `message` LONGTEXT NOT NULL,
    `logger_name` VARCHAR(255) NULL,
    `module` VARCHAR(255) NULL,
    `function_name` VARCHAR(255) NULL,
    `file_name` VARCHAR(255) NULL,
    `file_path` TEXT NULL,
    `line_no` INT NULL,
    `process_id` BIGINT NULL,
    `process_name` VARCHAR(255) NULL,
    `thread_id` BIGINT NULL,
    `thread_name` VARCHAR(255) NULL,
    `elapsed_ms` DOUBLE NOT NULL,
    `extra_json` JSON NULL,
    `exception_text` LONGTEXT NULL,
    `created_at_utc` TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`id`),
    INDEX `idx_logged_at_utc` (`logged_at_utc`),
    INDEX `idx_level_name` (`level_name`)
) ENGINE=InnoDB DEFAULT CHARSET={self._mysql.charset}
""".strip()

    def _insert_sql(self) -> str:
        quoted_columns = ", ".join(f"`{column}`" for column in _INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_INSERT_COLUMNS))
        return (
            f"INSERT INTO `{self._mysql.table}` ({quoted_columns}) "
            f"VALUES ({placeholders})"
        )

    def _isolate(
        self,
        records: list[DatabaseRecord],
        *,
        reason: str,
        error: Exception | None,
    ) -> None:
        if self._batch.overflow_policy == "drop" and reason == "queue_full":
            self._add_dropped(len(records))
            return

        path = Path(self._batch.dead_letter_path)
        failed_at = datetime.now(UTC).isoformat(timespec="microseconds")
        try:
            with self._dead_letter_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as stream:
                    for record in records:
                        payload = {
                            "failed_at_utc": failed_at,
                            "reason": reason,
                            "error": None if error is None else str(error),
                            "record": record.as_json_dict(),
                        }
                        stream.write(
                            json.dumps(payload, ensure_ascii=False, default=str) + "\n"
                        )
        except Exception as exc:
            self._add_dropped(len(records))
            self._internal_error(f"dead-letter write failed for {path}: {exc}")
        else:
            self._add_dead_lettered(len(records))

    def _close_pool_once(self) -> None:
        if self._pool_closed.is_set():
            return
        self._pool_closed.set()
        try:
            self._pool.close()
        except Exception as exc:
            self._internal_error(f"MySQL pool close failed: {exc}")

    def _increment(self, field: str) -> None:
        with self._stats_lock:
            setattr(self, field, getattr(self, field) + 1)

    def _add_written(self, count: int) -> None:
        with self._stats_lock:
            self._written += count
            self._batches += 1

    def _add_failed(self, count: int) -> None:
        with self._stats_lock:
            self._failed += count

    def _add_dead_lettered(self, count: int) -> None:
        with self._stats_lock:
            self._dead_lettered += count

    def _add_dropped(self, count: int) -> None:
        with self._stats_lock:
            self._dropped += count

    def _internal_error(self, message: str) -> None:
        if not self._batch.report_internal_errors:
            return
        try:
            sys.stderr.write(f"[sclog_lite] {message}\n")
            sys.stderr.flush()
        except Exception:
            pass
