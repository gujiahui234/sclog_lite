"""Console, file, and asynchronous MySQL logging built on Loguru."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from loguru import logger

from .config import BatchConfig, ConfigurationError, MySQLConfig, PoolConfig
from .core import get_log_file_path, get_writer_stats, setup_logger, shutdown
from .mysql_writer import WriterStats

try:
    __version__ = version("sclog-lite")
except PackageNotFoundError:
    __version__ = "0.1.0"

configure = setup_logger

__all__ = [
    "BatchConfig",
    "ConfigurationError",
    "MySQLConfig",
    "PoolConfig",
    "WriterStats",
    "__version__",
    "configure",
    "get_log_file_path",
    "get_writer_stats",
    "logger",
    "setup_logger",
    "shutdown",
]
