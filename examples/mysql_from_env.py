"""Write to console, file, and MySQL using environment configuration."""

from sclog_lite import get_writer_stats, setup_logger, shutdown

logger = setup_logger(mysql=True)
logger.bind(service="example", request_id="demo-001").info("three-way log output")
shutdown(timeout=10.0)
print(get_writer_stats())
