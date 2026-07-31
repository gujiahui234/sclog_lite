"""Public Loguru configuration helpers."""

from __future__ import annotations

import atexit
import sys
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger as _loguru_logger

from .config import BatchConfig, MySQLConfig, PoolConfig
from .mysql_writer import AsyncMySQLWriter, WriterStats
from .sink import MySQLSink

if TYPE_CHECKING:
    from loguru import Logger
else:
    Logger = type(_loguru_logger)


@dataclass(slots=True)
class _ManagedHandler:
    handler_id: int
    mysql_sink: MySQLSink | None = None


_state_lock = threading.RLock()
_managed_handlers: list[_ManagedHandler] = []
_last_log_file: Path | None = None
_last_writer_stats: WriterStats | None = None


def setup_logger(
    *,
    mysql: MySQLConfig | Mapping[str, Any] | bool | None = None,
    console: bool = True,
    file: bool = True,
    file_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    level: str | int = "INFO",
    pool: PoolConfig | Mapping[str, Any] | None = None,
    batch: BatchConfig | Mapping[str, Any] | None = None,
    console_options: Mapping[str, Any] | None = None,
    file_options: Mapping[str, Any] | None = None,
    mysql_handler_options: Mapping[str, Any] | None = None,
    reset: bool = True,
) -> Logger:
    """Configure console, file, and optional MySQL output.

    All option mappings are forwarded to :meth:`loguru.logger.add`. The returned
    object is Loguru's original global logger, so native methods remain available.

    Args:
        mysql: MySQL settings, ``True`` to load ``SCLOG_MYSQL_*`` variables,
            or ``None``/``False`` to disable database output.
        console: Add a standard-error console handler.
        file: Add a file handler.
        file_path: Exact file path. Overrides ``log_dir``.
        log_dir: Directory for the generated default filename. Defaults to
            ``Path.cwd() / "logs"``.
        level: Default level for all three managed handlers.
        pool: Pool settings or a mapping of :class:`PoolConfig` fields.
        batch: Batch settings or a mapping of :class:`BatchConfig` fields.
        console_options: Extra or overriding console-handler options.
        file_options: Extra or overriding file-handler options.
        mysql_handler_options: Extra or overriding MySQL-handler options.
        reset: Remove all existing Loguru handlers before adding managed ones.

    Returns:
        The original Loguru logger.

    Raises:
        ConfigurationError: If a supplied configuration is invalid.
        OSError: If the log directory cannot be created.
    """

    mysql_config = _coerce_mysql(mysql)
    pool_config = _coerce_pool(pool)
    batch_config = _coerce_batch(batch)
    resolved_file = _resolve_log_file(file_path=file_path, log_dir=log_dir) if file else None

    new_handlers: list[_ManagedHandler] = []
    unregistered_sink: MySQLSink | None = None
    global _last_log_file, _last_writer_stats

    with _state_lock:
        if reset:
            _loguru_logger.remove()
            _managed_handlers.clear()

        try:
            if console:
                options: dict[str, Any] = {
                    "level": level,
                    "enqueue": False,
                    "catch": True,
                }
                options.update(console_options or {})
                handler_id = _loguru_logger.add(sys.stderr, **options)
                new_handlers.append(_ManagedHandler(handler_id))

            if resolved_file is not None:
                options = {
                    "level": level,
                    "encoding": "utf-8",
                    "enqueue": True,
                    "catch": True,
                }
                options.update(file_options or {})
                handler_id = _loguru_logger.add(resolved_file, **options)
                new_handlers.append(_ManagedHandler(handler_id))

            if mysql_config is not None:
                writer = AsyncMySQLWriter(mysql_config, pool_config, batch_config)
                unregistered_sink = MySQLSink(writer)
                options = {
                    "level": level,
                    "format": "{message}",
                    "enqueue": False,
                    "catch": True,
                }
                options.update(mysql_handler_options or {})
                handler_id = _loguru_logger.add(unregistered_sink, **options)
                new_handlers.append(_ManagedHandler(handler_id, unregistered_sink))
                unregistered_sink = None
        except Exception:
            for registration in reversed(new_handlers):
                with suppress(ValueError):
                    _loguru_logger.remove(registration.handler_id)
            if unregistered_sink is not None:
                unregistered_sink.close()
            raise

        _managed_handlers.extend(new_handlers)
        _last_log_file = resolved_file
        _last_writer_stats = None

    return _loguru_logger


def shutdown(timeout: float = 10.0) -> bool:
    """Flush and remove all handlers managed by :func:`setup_logger`.

    Args:
        timeout: Maximum flush/close time for each MySQL writer.

    Returns:
        ``True`` if every MySQL writer stopped cleanly.
    """

    clean = True
    last_stats: WriterStats | None = None
    with _state_lock:
        registrations = list(_managed_handlers)
        _managed_handlers.clear()

    for registration in registrations:
        if registration.mysql_sink is not None:
            clean = registration.mysql_sink.close(timeout) and clean
            last_stats = registration.mysql_sink.stats()
        with suppress(ValueError):
            _loguru_logger.remove(registration.handler_id)
    if last_stats is not None:
        with _state_lock:
            global _last_writer_stats
            _last_writer_stats = last_stats
    return clean


def get_writer_stats() -> WriterStats | None:
    """Return statistics for the most recently configured MySQL sink."""

    with _state_lock:
        for registration in reversed(_managed_handlers):
            if registration.mysql_sink is not None:
                return registration.mysql_sink.stats()
        return _last_writer_stats


def get_log_file_path() -> Path | None:
    """Return the last file path created by :func:`setup_logger`."""

    with _state_lock:
        return _last_log_file


def _coerce_mysql(
    value: MySQLConfig | Mapping[str, Any] | bool | None,
) -> MySQLConfig | None:
    if value is None or value is False:
        return None
    if value is True:
        return MySQLConfig.from_env()
    if isinstance(value, MySQLConfig):
        return value
    return MySQLConfig.from_mapping(value)


def _coerce_pool(value: PoolConfig | Mapping[str, Any] | None) -> PoolConfig:
    if value is None:
        return PoolConfig()
    if isinstance(value, PoolConfig):
        return value
    return PoolConfig(**dict(value))


def _coerce_batch(value: BatchConfig | Mapping[str, Any] | None) -> BatchConfig:
    if value is None:
        return BatchConfig()
    if isinstance(value, BatchConfig):
        return value
    return BatchConfig(**dict(value))


def _resolve_log_file(
    *,
    file_path: str | Path | None,
    log_dir: str | Path | None,
) -> Path:
    if file_path is None:
        directory = Path.cwd() / "logs" if log_dir is None else Path(log_dir)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"default_{timestamp}.log"
    else:
        path = Path(file_path)
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _shutdown_at_exit() -> None:
    with suppress(Exception):
        shutdown()


atexit.register(_shutdown_at_exit)
