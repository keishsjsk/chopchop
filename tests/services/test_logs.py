import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from chopchop.services import logs


@pytest.fixture
def log_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(logs.LOG_ENV, str(tmp_path / "logs"))
    yield tmp_path / "logs"
    logs.shutdown()


def test_messages_go_to_the_file_by_level(log_folder: Path) -> None:
    path = logs.setup("warning")
    assert path == log_folder / "chopchop.log"
    logging.getLogger("chopchop.test").info("quiet")
    logging.getLogger("chopchop.test").warning("loud")
    logs.set_level("debug")  # уровень меняется на лету
    logging.getLogger("chopchop.test").debug("details")
    for handler in logs.log.handlers:
        handler.flush()
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "loud" in text and "details" in text and "quiet" not in text


def test_setup_twice_does_not_duplicate_handlers(log_folder: Path) -> None:
    logs.setup("error")
    count = len(logs.log.handlers)
    logs.setup("info")
    assert len(logs.log.handlers) == count


def test_unwritable_folder_is_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv(logs.LOG_ENV, str(blocker / "logs"))
    assert logs.setup("warning") is None


def test_excepthook_logs_and_chains(log_folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda kind, error, trace: seen.append(str(error)))
    path = logs.setup("error")
    logs.install_excepthook()
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    for handler in logs.log.handlers:
        handler.flush()
    assert seen == ["boom"]
    assert path is not None
    assert "boom" in path.read_text(encoding="utf-8")
