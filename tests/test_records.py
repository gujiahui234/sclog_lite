"""Tests for Loguru-record conversion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sclog_lite.records import DatabaseRecord


def test_database_record_preserves_structured_context() -> None:
    error = ValueError("broken")
    fake_message = SimpleNamespace(
        record={
            "time": datetime(2026, 7, 30, 12, 30, tzinfo=timezone(timedelta(hours=8))),
            "level": SimpleNamespace(name="INFO", no=20),
            "message": "hello",
            "name": "example",
            "module": "service",
            "function": "run",
            "file": SimpleNamespace(name="service.py", path="/app/service.py"),
            "line": 42,
            "process": SimpleNamespace(id=100, name="MainProcess"),
            "thread": SimpleNamespace(id=200, name="MainThread"),
            "elapsed": timedelta(seconds=1.25),
            "extra": {"request_id": "abc", "custom": object()},
            "exception": SimpleNamespace(
                type=ValueError,
                value=error,
                traceback=error.__traceback__,
            ),
        }
    )

    record = DatabaseRecord.from_loguru_message(fake_message)

    assert record.logged_at_utc == datetime(2026, 7, 30, 4, 30)
    assert record.level_name == "INFO"
    assert record.line_no == 42
    assert record.elapsed_ms == 1_250
    assert json.loads(record.extra_json)["request_id"] == "abc"
    assert "ValueError: broken" in (record.exception_text or "")


def test_database_record_json_dict_formats_timestamp() -> None:
    record = DatabaseRecord(
        logged_at_utc=datetime(2026, 7, 30, 4, 30, 1, 123456),
        level_name="INFO",
        level_no=20,
        message="hello",
        logger_name=None,
        module=None,
        function_name=None,
        file_name=None,
        file_path=None,
        line_no=None,
        process_id=None,
        process_name=None,
        thread_id=None,
        thread_name=None,
        elapsed_ms=0.0,
        extra_json="{}",
        exception_text=None,
    )

    assert record.as_json_dict()["logged_at_utc"] == "2026-07-30T04:30:01.123456Z"
