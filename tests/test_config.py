"""Tests for immutable configuration models."""

from __future__ import annotations

from pathlib import Path

import pytest

from sclog_lite import BatchConfig, ConfigurationError, MySQLConfig, PoolConfig


def test_mysql_config_hides_password_and_builds_connect_kwargs() -> None:
    config = MySQLConfig(
        user="logger",
        password="do-not-print-me",
        database="logs",
    )

    assert "do-not-print-me" not in repr(config)
    assert config.connect_kwargs()["password"] == "do-not-print-me"
    assert config.connect_kwargs()["autocommit"] is False


def test_mysql_config_rejects_unsafe_table_name() -> None:
    with pytest.raises(ConfigurationError, match="table"):
        MySQLConfig(
            user="logger",
            database="logs",
            table="logs; DROP TABLE users",
        )


def test_mysql_config_loads_environment() -> None:
    environ = {
        "SCLOG_MYSQL_HOST": "db.internal",
        "SCLOG_MYSQL_PORT": "3307",
        "SCLOG_MYSQL_USER": "logger",
        "SCLOG_MYSQL_PASSWORD": "secret",
        "SCLOG_MYSQL_DATABASE": "logs",
        "SCLOG_MYSQL_TABLE": "service_logs",
        "SCLOG_MYSQL_CREATE_TABLE": "false",
    }

    config = MySQLConfig.from_env(environ=environ)

    assert config.host == "db.internal"
    assert config.port == 3307
    assert config.user == "logger"
    assert config.database == "logs"
    assert config.table == "service_logs"
    assert config.create_table is False


def test_mysql_config_reports_missing_environment_values() -> None:
    with pytest.raises(ConfigurationError, match="SCLOG_MYSQL_USER"):
        MySQLConfig.from_env(environ={})


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: MySQLConfig(host="", user="logger", database="logs"),
            "host",
        ),
        (
            lambda: MySQLConfig(port=0, user="logger", database="logs"),
            "port",
        ),
        (
            lambda: MySQLConfig(user="", database="logs"),
            "user",
        ),
        (
            lambda: MySQLConfig(user="logger", database=""),
            "database",
        ),
        (
            lambda: MySQLConfig(user="logger", database="logs", charset=""),
            "charset",
        ),
        (
            lambda: MySQLConfig(
                user="logger",
                database="logs",
                connect_timeout=0,
            ),
            "connect_timeout",
        ),
        (
            lambda: MySQLConfig.from_env(
                environ={
                    "SCLOG_MYSQL_USER": "logger",
                    "SCLOG_MYSQL_DATABASE": "logs",
                    "SCLOG_MYSQL_PORT": "invalid",
                }
            ),
            "PORT",
        ),
        (
            lambda: MySQLConfig.from_env(
                environ={
                    "SCLOG_MYSQL_USER": "logger",
                    "SCLOG_MYSQL_DATABASE": "logs",
                    "SCLOG_MYSQL_CREATE_TABLE": "sometimes",
                }
            ),
            "CREATE_TABLE",
        ),
    ],
)
def test_invalid_mysql_configuration_raises(factory: object, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: PoolConfig(min_size=2, max_size=1), "min_size"),
        (lambda: PoolConfig(max_size=0), "max_size"),
        (lambda: PoolConfig(acquire_timeout=0), "acquire_timeout"),
        (lambda: PoolConfig(recycle_seconds=0), "recycle_seconds"),
        (lambda: BatchConfig(batch_size=0), "batch_size"),
        (lambda: BatchConfig(flush_interval=0), "flush_interval"),
        (lambda: BatchConfig(batch_size=10, queue_size=5), "queue_size"),
        (lambda: BatchConfig(max_retries=-1), "max_retries"),
        (lambda: BatchConfig(retry_backoff=-1), "retry_backoff"),
        (
            lambda: BatchConfig(retry_backoff=2, retry_backoff_max=1),
            "retry_backoff_max",
        ),
        (lambda: BatchConfig(shutdown_timeout=0), "shutdown_timeout"),
    ],
)
def test_invalid_worker_configuration_raises(factory: object, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        factory()  # type: ignore[operator]


def test_batch_config_normalizes_dead_letter_path() -> None:
    config = BatchConfig(dead_letter_path="logs/failed.jsonl")

    assert config.dead_letter_path == Path("logs/failed.jsonl")
