"""Write one log message to console and a generated file."""

from sclog_lite import setup_logger, shutdown

logger = setup_logger()
logger.info("sclog_lite is ready")
shutdown()
