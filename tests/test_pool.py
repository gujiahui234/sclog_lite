"""Tests for the native PyMySQL connection pool."""

from __future__ import annotations

from typing import Any

import pytest

from sclog_lite import MySQLConfig, PoolConfig
from sclog_lite.pool import MySQLConnectionPool, PoolClosedError


class FakeConnection:
    """Minimal PyMySQL-compatible connection used by pool tests."""

    def __init__(self) -> None:
        self.open = True
        self.pings = 0
        self.rollbacks = 0

    def ping(self, reconnect: bool) -> None:
        assert reconnect is False
        self.pings += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.open = False


def test_pool_reuses_and_health_checks_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeConnection] = []

    def connect(**kwargs: Any) -> FakeConnection:
        assert kwargs["autocommit"] is False
        connection = FakeConnection()
        created.append(connection)
        return connection

    monkeypatch.setattr("sclog_lite.pool.pymysql.connect", connect)
    pool = MySQLConnectionPool(
        MySQLConfig(user="logger", database="logs"),
        PoolConfig(max_size=2),
    )

    with pool.connection() as first:
        assert first is created[0]
    with pool.connection() as second:
        assert second is first

    assert len(created) == 1
    assert created[0].pings == 1
    pool.close()
    assert created[0].open is False


def test_pool_discards_connection_after_context_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeConnection] = []

    def connect(**kwargs: Any) -> FakeConnection:
        connection = FakeConnection()
        created.append(connection)
        return connection

    monkeypatch.setattr("sclog_lite.pool.pymysql.connect", connect)
    pool = MySQLConnectionPool(
        MySQLConfig(user="logger", database="logs"),
        PoolConfig(max_size=1),
    )

    with pytest.raises(RuntimeError, match="failure"), pool.connection():
        raise RuntimeError("failure")

    assert created[0].rollbacks == 1
    assert created[0].open is False
    assert pool.size == 0
    pool.close()


def test_closed_pool_rejects_acquisition() -> None:
    pool = MySQLConnectionPool(
        MySQLConfig(user="logger", database="logs"),
        PoolConfig(),
    )
    pool.close()

    with pytest.raises(PoolClosedError):
        pool.acquire()
