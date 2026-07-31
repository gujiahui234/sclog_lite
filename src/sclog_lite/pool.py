"""A small thread-safe connection pool built directly on PyMySQL."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass

import pymysql
from pymysql.connections import Connection

from .config import MySQLConfig, PoolConfig


class PoolClosedError(RuntimeError):
    """Raised when a connection is requested from a closed pool."""


class PoolTimeoutError(TimeoutError):
    """Raised when no connection becomes available before the timeout."""


@dataclass(slots=True)
class _PooledConnection:
    connection: Connection
    created_at: float


class MySQLConnectionPool:
    """A bounded, thread-safe PyMySQL connection pool.

    The pool creates connections lazily. ``warmup()`` can populate
    ``PoolConfig.min_size`` from a background thread without making application
    startup depend on database availability.
    """

    def __init__(self, mysql: MySQLConfig, pool: PoolConfig) -> None:
        """Initialize an empty connection pool.

        Args:
            mysql: Database connection settings.
            pool: Pool sizing and health-check settings.
        """

        self._mysql = mysql
        self._config = pool
        self._idle: queue.LifoQueue[_PooledConnection] = queue.LifoQueue(
            maxsize=pool.max_size
        )
        self._state_lock = threading.Lock()
        self._created = 0
        self._closed = False

    @property
    def size(self) -> int:
        """Return the number of live idle and checked-out connections."""

        with self._state_lock:
            return self._created

    @property
    def idle_size(self) -> int:
        """Return the approximate number of idle connections."""

        return self._idle.qsize()

    def warmup(self) -> None:
        """Create up to ``min_size`` idle connections.

        Raises:
            Exception: Propagates a PyMySQL connection error. Callers should run
                warmup away from the logging call path.
        """

        while self.size < self._config.min_size:
            pooled = self._create_reserved()
            self._release(pooled)

    def acquire(self) -> _PooledConnection:
        """Acquire a healthy connection.

        Returns:
            A private pooled-connection wrapper.

        Raises:
            PoolClosedError: If the pool is closed.
            PoolTimeoutError: If the pool remains exhausted.
            pymysql.MySQLError: If a new connection cannot be established.
        """

        deadline = time.monotonic() + self._config.acquire_timeout
        while True:
            self._ensure_open()
            try:
                pooled = self._idle.get_nowait()
            except queue.Empty:
                if self._reserve_slot():
                    try:
                        return self._connect_reserved_slot()
                    except Exception:
                        self._unreserve_slot()
                        raise

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PoolTimeoutError(
                        f"No MySQL connection became available within "
                        f"{self._config.acquire_timeout:.3f}s"
                    ) from None
                try:
                    pooled = self._idle.get(timeout=remaining)
                except queue.Empty as exc:
                    raise PoolTimeoutError(
                        f"No MySQL connection became available within "
                        f"{self._config.acquire_timeout:.3f}s"
                    ) from exc

            if self._is_usable(pooled):
                return pooled
            self._discard(pooled)

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Yield a connection and return or discard it automatically.

        Yields:
            A live PyMySQL connection.
        """

        pooled = self.acquire()
        try:
            yield pooled.connection
        except BaseException:
            with suppress(Exception):
                pooled.connection.rollback()
            self._discard(pooled)
            raise
        else:
            self._release(pooled)

    def close(self) -> None:
        """Close all idle connections and reject new acquisitions."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True

        while True:
            try:
                pooled = self._idle.get_nowait()
            except queue.Empty:
                break
            self._discard(pooled)

    def _ensure_open(self) -> None:
        with self._state_lock:
            if self._closed:
                raise PoolClosedError("MySQL connection pool is closed")

    def _reserve_slot(self) -> bool:
        with self._state_lock:
            if self._closed:
                raise PoolClosedError("MySQL connection pool is closed")
            if self._created >= self._config.max_size:
                return False
            self._created += 1
            return True

    def _unreserve_slot(self) -> None:
        with self._state_lock:
            self._created = max(0, self._created - 1)

    def _connect_reserved_slot(self) -> _PooledConnection:
        connection = pymysql.connect(**self._mysql.connect_kwargs())
        return _PooledConnection(connection=connection, created_at=time.monotonic())

    def _create_reserved(self) -> _PooledConnection:
        if not self._reserve_slot():
            raise PoolTimeoutError("MySQL pool is already at max_size")
        try:
            return self._connect_reserved_slot()
        except Exception:
            self._unreserve_slot()
            raise

    def _is_usable(self, pooled: _PooledConnection) -> bool:
        if time.monotonic() - pooled.created_at >= self._config.recycle_seconds:
            return False
        if not pooled.connection.open:
            return False
        if not self._config.ping_on_acquire:
            return True
        try:
            pooled.connection.ping(reconnect=False)
        except Exception:
            return False
        return True

    def _release(self, pooled: _PooledConnection) -> None:
        with self._state_lock:
            closed = self._closed
        if closed or not pooled.connection.open:
            self._discard(pooled)
            return
        try:
            self._idle.put_nowait(pooled)
        except queue.Full:  # pragma: no cover - protects against invariant violations
            self._discard(pooled)

    def _discard(self, pooled: _PooledConnection) -> None:
        with suppress(Exception):
            pooled.connection.close()
        self._unreserve_slot()
