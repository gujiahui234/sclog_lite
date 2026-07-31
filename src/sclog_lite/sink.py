"""Custom Loguru sink backed by :class:`AsyncMySQLWriter`."""

from __future__ import annotations

import asyncio
from typing import Any

from .mysql_writer import AsyncMySQLWriter, WriterStats
from .records import DatabaseRecord


class MySQLSink:
    """Convert Loguru messages and submit them to the background writer."""

    def __init__(self, writer: AsyncMySQLWriter) -> None:
        """Store the writer used by the sink."""

        self._writer = writer

    def write(self, message: Any) -> None:
        """Handle one message without waiting for database I/O.

        Args:
            message: Loguru message object containing a structured ``record``.
        """

        try:
            record = DatabaseRecord.from_loguru_message(message)
            self._writer.submit(record)
        except Exception:
            # Loguru also receives ``catch=True`` for this sink. This explicit
            # boundary keeps conversion failures independent of other handlers.
            return

    def stop(self) -> None:
        """Flush queued records when Loguru removes this sink."""

        self._writer.close()

    async def complete(self) -> None:
        """Integrate the custom writer with ``await logger.complete()``."""

        await asyncio.to_thread(self._writer.flush)

    def close(self, timeout: float | None = None) -> bool:
        """Close the underlying writer explicitly."""

        return self._writer.close(timeout)

    def stats(self) -> WriterStats:
        """Return writer counters."""

        return self._writer.stats()
