"""Conversion of Loguru messages into database-safe records."""

from __future__ import annotations

import json
import traceback
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


def _json_default(value: object) -> str:
    """Return a stable string fallback for non-JSON-native values."""

    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive fallback for hostile objects
        return f"<unprintable {type(value).__name__}>"


def _exception_text(exception: object) -> str | None:
    """Format a Loguru exception record without raising.

    Args:
        exception: Loguru's ``RecordException`` value.

    Returns:
        A traceback string, or ``None`` when no exception is attached.
    """

    if exception is None:
        return None
    try:
        exception_type = getattr(exception, "type", None)
        exception_value = getattr(exception, "value", None)
        exception_traceback = getattr(exception, "traceback", None)
        if exception_type is not None:
            return "".join(
                traceback.format_exception(
                    exception_type,
                    exception_value,
                    exception_traceback,
                )
            )
        return _json_default(exception)
    except Exception:  # pragma: no cover - exception formatting must be isolated
        return "<exception formatting failed>"


@dataclass(frozen=True, slots=True)
class DatabaseRecord:
    """A serializable snapshot of a Loguru record."""

    logged_at_utc: datetime
    level_name: str
    level_no: int
    message: str
    logger_name: str | None
    module: str | None
    function_name: str | None
    file_name: str | None
    file_path: str | None
    line_no: int | None
    process_id: int | None
    process_name: str | None
    thread_id: int | None
    thread_name: str | None
    elapsed_ms: float
    extra_json: str
    exception_text: str | None

    @classmethod
    def from_loguru_message(cls, message: Any) -> DatabaseRecord:
        """Copy a Loguru message into primitive, database-safe values.

        Args:
            message: Object passed to a custom Loguru sink.

        Returns:
            A database record detached from Loguru internals.
        """

        record: Mapping[str, Any] = message.record
        logged_at = record["time"]
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=UTC)
        logged_at_utc = logged_at.astimezone(UTC).replace(tzinfo=None)

        level = record["level"]
        file_record = record["file"]
        process = record["process"]
        thread = record["thread"]
        elapsed = record["elapsed"]
        extra_json = json.dumps(
            dict(record.get("extra", {})),
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )

        return cls(
            logged_at_utc=logged_at_utc,
            level_name=str(level.name),
            level_no=int(level.no),
            message=str(record["message"]),
            logger_name=None if record.get("name") is None else str(record["name"]),
            module=None if record.get("module") is None else str(record["module"]),
            function_name=(
                None if record.get("function") is None else str(record["function"])
            ),
            file_name=None if file_record is None else str(file_record.name),
            file_path=None if file_record is None else str(file_record.path),
            line_no=None if record.get("line") is None else int(record["line"]),
            process_id=None if process is None else int(process.id),
            process_name=None if process is None else str(process.name),
            thread_id=None if thread is None else int(thread.id),
            thread_name=None if thread is None else str(thread.name),
            elapsed_ms=float(elapsed.total_seconds() * 1_000),
            extra_json=extra_json,
            exception_text=_exception_text(record.get("exception")),
        )

    def as_mysql_parameters(self) -> tuple[object, ...]:
        """Return values in the order used by the MySQL INSERT statement."""

        return (
            self.logged_at_utc,
            self.level_name,
            self.level_no,
            self.message,
            self.logger_name,
            self.module,
            self.function_name,
            self.file_name,
            self.file_path,
            self.line_no,
            self.process_id,
            self.process_name,
            self.thread_id,
            self.thread_name,
            self.elapsed_ms,
            self.extra_json,
            self.exception_text,
        )

    def as_json_dict(self) -> dict[str, object]:
        """Return a JSON-compatible dictionary for dead-letter storage."""

        result = asdict(self)
        result["logged_at_utc"] = self.logged_at_utc.isoformat(timespec="microseconds") + "Z"
        return result
