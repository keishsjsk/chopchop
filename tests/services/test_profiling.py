import time
from collections.abc import Iterator

import pytest
from pytestqt.qtbot import QtBot

from chopchop.services import profiling


@pytest.fixture
def profiling_on() -> Iterator[None]:
    profiling.set_enabled(True)
    profiling.clear()
    yield
    profiling.set_enabled(False)
    profiling.clear()


def test_stage_records_elapsed_time_when_enabled(profiling_on: None) -> None:
    with profiling.stage("demo"):
        time.sleep(0.02)
    ((name, milliseconds),) = profiling.records()
    assert name == "demo"
    assert milliseconds >= 15


def test_stage_costs_nothing_when_disabled() -> None:
    profiling.set_enabled(False)
    profiling.clear()
    with profiling.stage("demo"):
        pass
    assert profiling.records() == []


def test_summary_groups_repeated_stages(profiling_on: None) -> None:
    for value in (10.0, 30.0):
        profiling.record("x", value)
    assert profiling.summary()["x"] == (2, 20.0, 30.0)


def test_enabled_by_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    monkeypatch.setenv("CHOPCHOP_PROFILE", "1")
    reloaded = importlib.reload(profiling)
    assert reloaded.enabled()
    monkeypatch.delenv("CHOPCHOP_PROFILE")
    assert not importlib.reload(profiling).enabled()


def test_watchdog_reports_a_blocked_event_loop(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer

    watchdog = profiling.LoopWatchdog(threshold_ms=200)  # запас на медленные машины CI
    watchdog.start()
    qtbot.wait(100)  # цикл свободен: зависаний нет
    assert watchdog.stalls == []
    QTimer.singleShot(0, lambda: time.sleep(0.6))  # поток интерфейса занят 600 мс
    qtbot.wait(1000)
    watchdog.stop()
    assert len(watchdog.stalls) == 1
    assert 200 <= watchdog.stalls[0] <= 1500
