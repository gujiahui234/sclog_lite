"""Opt-in integration test against a real MySQL database."""

from __future__ import annotations

import os
import uuid

import pymysql
import pytest

from sclog_lite import MySQLConfig, get_writer_stats, logger, setup_logger, shutdown

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("SCLOG_TEST_MYSQL") != "1",
    reason="set SCLOG_TEST_MYSQL=1 to run the MySQL integration test",
)
def test_real_mysql_round_trip() -> None:
    config = MySQLConfig.from_env()
    marker = f"sclog-lite-integration-{uuid.uuid4()}"
    setup_logger(mysql=config, console=False, file=False)

    logger.bind(integration=True).info(marker)
    assert shutdown(timeout=10.0)
    stats = get_writer_stats()

    with (
        pymysql.connect(**config.connect_kwargs()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            f"SELECT COUNT(*) FROM `{config.table}` WHERE `message` = %s",
            (marker,),
        )
        count = cursor.fetchone()[0]

    assert count == 1
    assert stats is not None
    assert stats.written >= 1
