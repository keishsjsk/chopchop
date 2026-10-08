import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from quickedit.ui.trim_bar import TrimBar, format_precise


def _bar(qtbot: QtBot) -> TrimBar:
    bar = TrimBar()
    qtbot.addWidget(bar)
    bar.resize(624, 64)  # дорожка 600 пикселей, поле по 12
    bar.show()
    bar.set_clip(60.0, 10.0, 40.0, [None] * 6)
    return bar


def _x(seconds: float) -> int:
    return round(12 + seconds / 60.0 * 600)


def test_format_precise() -> None:
    assert format_precise(0) == "0:00.0"
    assert format_precise(65.34) == "1:05.3"
    assert format_precise(-1) == "0:00.0"


def test_clicking_track_requests_seek(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    targets: list[float] = []
    bar.seekRequested.connect(targets.append)
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(25), 32))
    assert targets[-1] == pytest.approx(25.0, abs=0.2)


def test_dragging_start_handle_trims(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    live: list[tuple[float, float]] = []
    committed: list[tuple[float, float]] = []
    bar.trimming.connect(lambda a, b: live.append((a, b)))
    bar.trimCommitted.connect(lambda a, b: committed.append((a, b)))
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(10), 32))
    QTest.mouseMove(bar, QPoint(_x(20), 32))
    assert live
    assert not committed  # пока кнопка зажата, в историю ничего не пишется
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(20), 32))
    assert len(committed) == 1
    start, end = committed[0]
    assert start == pytest.approx(20.0, abs=0.2)
    assert end == 40.0


def test_end_handle_cannot_cross_start(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    committed: list[tuple[float, float]] = []
    bar.trimCommitted.connect(lambda a, b: committed.append((a, b)))
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(40), 32))
    QTest.mouseMove(bar, QPoint(_x(2), 32))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(2), 32))
    start, end = committed[0]
    assert start == 10.0
    assert end == pytest.approx(10.1)


def test_seek_click_does_not_change_trim(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    committed: list[tuple[float, float]] = []
    bar.trimCommitted.connect(lambda a, b: committed.append((a, b)))
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(30), 32))
    assert not committed
    assert (bar.start, bar.end) == (10.0, 40.0)


def test_set_range_ignored_while_dragging(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(10), 32))
    bar.set_range(0.0, 5.0)  # обновление из проекта не должно прерывать перетаскивание
    assert bar.end == 40.0
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(_x(10), 32))
    bar.set_range(0.0, 5.0)
    assert bar.end == 5.0
