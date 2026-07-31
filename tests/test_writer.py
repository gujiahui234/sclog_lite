"""Tests for asynchronous MySQL batching and failure isolation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sclog_lite import BatchConfig, MySQLConfig, PoolConfig
from sclog_lite.mysql_writer import AsyncMySQLWriter
from sclog_lite.records import DatabaseRecord


def make_record(message: str) -> DatabaseRecord:
    """Create a deterministic record for writer tests."""

    return DatabaseRecord(
        logged_at_utc=datetime(2026, 7, 30, 4, 30),
        level_name="INFO",
        level_no=20,
        message=message,
        logger_name="test",
        module="test_writer",
        function_name="test",
        file_name="test_writer.py",
        file_path="/tests/test_writer.py",
        line_no=1,
        process_id=1,
        process_name="pytest",
        thread_id=1,
        thread_name="MainThread",
        elapsed_ms=1.0,
        extra_json='{"case":"unit"}',
        exception_text=None,
    )


class FakeCursor:
    """Capture SQL sent by the writer."""

    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.execute_calls.append(sql)

    def executemany(self, sql: str, values: list[tuple[object, ...]]) -> None:
        self.executemany_calls.append((sql, values))


class FakeConnection:
    """Connection object shared by a fake pool."""

    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class FakePool:
    """Successful pool used to verify batching."""

    def __init__(self) -> None:
        self.connection_instance = FakeConnection()
        self.warmed = False
        self.closed = False

    def warmup(self) -> None:
        self.warmed = True

    @contextmanager
    def connection(self) -> Iterator[FakeConnection]:
        yield self.connection_instance

    def close(self) -> None:
        self.closed = True


class FailingPool:
    """Pool that simulates a permanently unavailable database."""

    def __init__(self) -> None:
        self.closed = False

    def warmup(self) -> None:
        return None

    @contextmanager
    def connection(self) -> Iterator[FakeConnection]:
        raise RuntimeError("database unavailable")
        yield FakeConnection()  # pragma: no cover

    def close(self) -> None:
        self.closed = True


def test_writer_batches_records_and_creates_table(tmp_path: Path) -> None:
    pool = FakePool()
    writer = AsyncMySQLWriter(
        MySQLConfig(user="logger", database="logs"),
        PoolConfig(),
        BatchConfig(
            batch_size=2,
            queue_size=10,
            flush_interval=0.01,
            dead_letter_path=tmp_path / "failed.jsonl",
            report_internal_errors=False,
        ),
        pool=pool,
    )

    assert writer.submit(make_record("first"))
    assert writer.submit(make_record("second"))
    assert writer.flush(timeout=2.0)
    assert writer.close(timeout=2.0)

    cursor = pool.connection_instance.cursor_instance
    assert pool.warmed
    assert pool.closed
    assert len(cursor.execute_calls) == 1
    assert "CREATE TABLE IF NOT EXISTS `sclog_entries`" in cursor.execute_calls[0]
    assert len(cursor.executemany_calls) == 1
    assert len(cursor.executemany_calls[0][1]) == 2
    assert pool.connection_instance.commits == 1
    assert writer.stats().written == 2
    assert writer.stats().batches == 1


def test_writer_isolates_failed_batch_to_jsonl(tmp_path: Path) -> None:
    dead_letter = tmp_path / "isolation" / "failed.jsonl"
    writer = AsyncMySQLWriter(
        MySQLConfig(user="logger", database="logs"),
        PoolConfig(),
        BatchConfig(
            batch_size=1,
            queue_size=10,
            flush_interval=0.01,
            max_retries=1,
            retry_backoff=0,
            dead_letter_path=dead_letter,
            report_internal_errors=False,
        ),
        pool=FailingPool(),
    )

    assert writer.submit(make_record("must survive"))
    assert writer.flush(timeout=2.0)
    assert writer.close(timeout=2.0)

    payload = json.loads(dead_letter.read_text(encoding="utf-8").splitlines()[0])
    assert payload["reason"] == "mysql_batch_failed"
    assert payload["record"]["message"] == "must survive"
    assert writer.stats().failed == 1
    assert writer.stats().dead_lettered == 1
    assert writer.stats().retries == 1
