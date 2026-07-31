"""Configuration models for :mod:`sclog_lite`."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigurationError(ValueError):
    """Raised when a configuration value is invalid."""


def _env_bool(value: str, *, name: str) -> bool:
    """Parse a boolean environment variable.

    Args:
        value: Raw environment variable value.
        name: Variable name used in an error message.

    Returns:
        The parsed boolean.

    Raises:
        ConfigurationError: If the value is not a supported boolean spelling.
    """

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be one of: 1/0, true/false, yes/no, on/off")


@dataclass(frozen=True, slots=True)
class MySQLConfig:
    """MySQL connection and destination-table configuration.

    Attributes:
        host: MySQL server hostname or IP address.
        port: MySQL TCP port.
        user: Database username.
        password: Database password. It is excluded from ``repr``.
        database: Database containing the log table.
        table: Destination table name.
        charset: Connection character set.
        connect_timeout: Connection timeout in seconds.
        read_timeout: Socket read timeout in seconds.
        write_timeout: Socket write timeout in seconds.
        unix_socket: Optional Unix-domain socket path.
        ssl: Optional ``pymysql.connect()`` SSL mapping.
        create_table: Whether to create the destination table automatically.
    """

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = ""
    password: str = field(default="", repr=False)
    database: str = ""
    table: str = "sclog_entries"
    charset: str = "utf8mb4"
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    write_timeout: float = 10.0
    unix_socket: str | None = None
    ssl: Mapping[str, Any] | None = None
    create_table: bool = True

    def __post_init__(self) -> None:
        """Validate the immutable configuration after initialization."""

        if not self.host and not self.unix_socket:
            raise ConfigurationError("host is required when unix_socket is not set")
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("port must be between 1 and 65535")
        if not self.user:
            raise ConfigurationError("user is required")
        if not self.database:
            raise ConfigurationError("database is required")
        if not _MYSQL_IDENTIFIER.fullmatch(self.table):
            raise ConfigurationError(
                "table must start with a letter or underscore and contain only "
                "ASCII letters, digits, and underscores"
            )
        if not _MYSQL_IDENTIFIER.fullmatch(self.charset):
            raise ConfigurationError(
                "charset must contain only ASCII letters, digits, and underscores"
            )
        for name in ("connect_timeout", "read_timeout", "write_timeout"):
            if getattr(self, name) <= 0:
                raise ConfigurationError(f"{name} must be greater than zero")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> MySQLConfig:
        """Create a configuration from a mapping.

        Args:
            values: Keys matching :class:`MySQLConfig` field names.

        Returns:
            A validated configuration.
        """

        return cls(**dict(values))

    @classmethod
    def from_env(
        cls,
        prefix: str = "SCLOG_MYSQL_",
        environ: Mapping[str, str] | None = None,
    ) -> MySQLConfig:
        """Load a configuration from environment variables.

        Args:
            prefix: Environment-variable prefix.
            environ: Optional mapping used instead of :data:`os.environ`.

        Returns:
            A validated configuration.

        Raises:
            ConfigurationError: If a required value is missing or malformed.
        """

        source = os.environ if environ is None else environ

        def read(name: str, default: str | None = None) -> str | None:
            return source.get(f"{prefix}{name}", default)

        user = read("USER")
        database = read("DATABASE")
        missing = [
            f"{prefix}{name}"
            for name, value in (("USER", user), ("DATABASE", database))
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Missing required MySQL environment variable(s): " + ", ".join(missing)
            )

        try:
            port = int(read("PORT", "3306") or "3306")
        except ValueError as exc:
            raise ConfigurationError(f"{prefix}PORT must be an integer") from exc

        create_table_raw = read("CREATE_TABLE", "true") or "true"
        return cls(
            host=read("HOST", "127.0.0.1") or "127.0.0.1",
            port=port,
            user=user or "",
            password=read("PASSWORD", "") or "",
            database=database or "",
            table=read("TABLE", "sclog_entries") or "sclog_entries",
            charset=read("CHARSET", "utf8mb4") or "utf8mb4",
            unix_socket=read("UNIX_SOCKET"),
            create_table=_env_bool(
                create_table_raw,
                name=f"{prefix}CREATE_TABLE",
            ),
        )

    def connect_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments accepted by :func:`pymysql.connect`.

        Returns:
            A new dictionary that does not expose itself through ``repr``.
        """

        result: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "write_timeout": self.write_timeout,
            "autocommit": False,
        }
        if self.unix_socket is not None:
            result["unix_socket"] = self.unix_socket
        if self.ssl is not None:
            result["ssl"] = dict(self.ssl)
        return result


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Thread-safe PyMySQL connection-pool settings."""

    min_size: int = 0
    max_size: int = 5
    acquire_timeout: float = 5.0
    recycle_seconds: float = 1_800.0
    ping_on_acquire: bool = True

    def __post_init__(self) -> None:
        """Validate pool limits."""

        if self.min_size < 0:
            raise ConfigurationError("min_size must be zero or greater")
        if self.max_size < 1:
            raise ConfigurationError("max_size must be one or greater")
        if self.min_size > self.max_size:
            raise ConfigurationError("min_size must not exceed max_size")
        if self.acquire_timeout <= 0:
            raise ConfigurationError("acquire_timeout must be greater than zero")
        if self.recycle_seconds <= 0:
            raise ConfigurationError("recycle_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class BatchConfig:
    """Asynchronous batch-writer and failure-isolation settings."""

    batch_size: int = 100
    flush_interval: float = 1.0
    queue_size: int = 10_000
    max_retries: int = 3
    retry_backoff: float = 0.25
    retry_backoff_max: float = 5.0
    overflow_policy: Literal["dead_letter", "drop"] = "dead_letter"
    dead_letter_path: Path | str = Path("logs/sclog_lite_failed.jsonl")
    shutdown_timeout: float = 10.0
    report_internal_errors: bool = True

    def __post_init__(self) -> None:
        """Validate batch values and normalize the dead-letter path."""

        if self.batch_size < 1:
            raise ConfigurationError("batch_size must be one or greater")
        if self.flush_interval <= 0:
            raise ConfigurationError("flush_interval must be greater than zero")
        if self.queue_size < self.batch_size:
            raise ConfigurationError("queue_size must be at least batch_size")
        if self.max_retries < 0:
            raise ConfigurationError("max_retries must be zero or greater")
        if self.retry_backoff < 0:
            raise ConfigurationError("retry_backoff must be zero or greater")
        if self.retry_backoff_max < self.retry_backoff:
            raise ConfigurationError("retry_backoff_max must be at least retry_backoff")
        if self.shutdown_timeout <= 0:
            raise ConfigurationError("shutdown_timeout must be greater than zero")
        object.__setattr__(self, "dead_letter_path", Path(self.dead_letter_path))
