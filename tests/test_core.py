"""End-to-end tests for the public setup function."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from sclog_lite import (
    WriterStats,
    get_log_file_path,
    get_writer_stats,
    logger,
    setup_logger,
    shutdown,
)


def test_default_file_path_is_created_and_receives_log(tmp_path: Path) -> None:
    configured = setup_logger(
        console=False,
        log_dir=tmp_path,
        file_options={"enqueue": False, "format": "{message}"},
    )
    configured.info("written to default file")
    path = get_log_file_path()
    assert shutdown()

    assert path is not None
    assert path.parent == tmp_path.resolve()
    assert re.fullmatch(r"default_\d{8}-\d{6}\.log", path.name)
    assert "written to default file" in path.read_text(encoding="utf-8")


def test_exact_file_path_creates_parent_directories(tmp_path: Path) -> None:
    requested = tmp_path / "nested" / "application.log"
    setup_logger(
        console=False,
        file_path=requested,
        file_options={"enqueue": False, "format": "{message}"},
    ).info("nested")
    assert shutdown()

    assert requested.read_text(encoding="utf-8").strip() == "nested"


def test_one_configuration_writes_to_all_three_sinks(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_writers: list[FakeWriter] = []

    class FakeWriter:
        """Capture database records without connecting to MySQL."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.records: list[Any] = []
            self.closed = False
            fake_writers.append(self)

        def submit(self, record: Any) -> bool:
            self.records.append(record)
            return True

        def flush(self, timeout: float | None = None) -> bool:
            return True

        def close(self, timeout: float | None = None) -> bool:
            self.closed = True
            return True

        def stats(self) -> WriterStats:
            return WriterStats(
                submitted=len(self.records),
                written=len(self.records),
                failed=0,
                dead_lettered=0,
                dropped=0,
                batches=1,
                retries=0,
                queue_size=0,
            )

    monkeypatch.setattr("sclog_lite.core.AsyncMySQLWriter", FakeWriter)
    output = tmp_path / "three-way.log"
    configured = setup_logger(
        mysql={"user": "logger", "database": "logs"},
        pool={"max_size": 2},
        batch={"batch_size": 1, "queue_size": 10},
        file_path=output,
        console_options={"colorize": False, "format": "{message}"},
        file_options={"enqueue": False, "format": "{message}"},
    )

    assert configured is logger
    configured.bind(request_id="abc").info("three-way")
    assert get_writer_stats() is not None
    assert get_writer_stats().submitted == 1  # type: ignore[union-attr]
    assert shutdown()

    assert "three-way" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8").strip() == "three-way"
    assert fake_writers[0].records[0].message == "three-way"
    assert fake_writers[0].records[0].extra_json == '{"request_id":"abc"}'
    assert fake_writers[0].closed
    assert get_writer_stats() is not None
