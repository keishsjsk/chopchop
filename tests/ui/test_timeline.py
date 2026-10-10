"""Полоса блоков: раскладка, выбор, растяжение краёв, перенос, перемотка, масштаб, меню."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QImage, QMouseEvent, QWheelEvent
from pytestqt.qtbot import QtBot

from chopchop.ui.timeline import GAP, RULER_H, Timeline, TimelineBlock, range_label

A = Path("a.mp4")
LEFT = Qt.MouseButton.LeftButton


def _bar(qtbot: QtBot, blocks: list[TimelineBlock] | None = None, selected: int | None = None):  # type: ignore[no-untyped-def]
    bar = Timeline()
    qtbot.addWidget(bar)
    bar.resize(900, 110)
    bar.show()
    bar.set_blocks(
        blocks or [TimelineBlock(A, 60.0, 0.0, 20.0), TimelineBlock(A, 60.0, 20.0, 40.0)],
        selected,
    )
    return bar


def _send(bar: Timeline, kind: QEvent.Type, x: float, y: float | None = None) -> None:
    point = QPointF(x, bar._track().center().y() if y is None else y)
    buttons = LEFT if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    button = LEFT if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    event = QMouseEvent(
        kind, point, bar.mapToGlobal(point), button, buttons, Qt.KeyboardModifier.NoModifier
    )
    handler = {
        QEvent.Type.MouseButtonPress: bar.mousePressEvent,
        QEvent.Type.MouseMove: bar.mouseMoveEvent,
        QEvent.Type.MouseButtonRelease: bar.mouseReleaseEvent,
    }[kind]
    handler(event)


def _drag(bar: Timeline, start: float, end: float, y: float | None = None, steps: int = 6) -> None:
    _send(bar, QEvent.Type.MouseButtonPress, start, y)
    for i in range(1, steps + 1):
        _send(bar, QEvent.Type.MouseMove, start + (end - start) * i / steps, y)
    _send(bar, QEvent.Type.MouseButtonRelease, end, y)


def test_blocks_are_laid_out_in_order_with_a_seam_between(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    first, second = bar.block_rect(0), bar.block_rect(1)
    assert first.right() < second.left()
    assert second.left() - first.right() == pytest.approx(GAP, abs=0.5)
    assert bar.duration == pytest.approx(40.0)
    assert bar.block_at(first.center().x()) == 0 and bar.block_at(second.center().x()) == 1
    assert bar.time_at(second.center().x()) == pytest.approx(30.0, abs=1.0)


def test_click_selects_a_block_and_seeks_into_it(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    picked: list[int] = []
    seeks: list[float] = []
    bar.blockSelected.connect(picked.append)
    bar.seekFinished.connect(seeks.append)
    x = bar.block_rect(1).center().x()
    _send(bar, QEvent.Type.MouseButtonPress, x)
    _send(bar, QEvent.Type.MouseButtonRelease, x)
    assert picked == [1] and bar.selected == 1
    assert seeks and seeks[-1] == pytest.approx(bar.time_at(x))


def test_click_between_blocks_and_outside_clears_selection(qtbot: QtBot) -> None:
    bar = _bar(qtbot, selected=0)
    cleared: list[bool] = []
    bar.selectionCleared.connect(lambda: cleared.append(True))
    _send(bar, QEvent.Type.MouseButtonPress, bar.width() - 1)  # за концом ролика
    _send(bar, QEvent.Type.MouseButtonRelease, bar.width() - 1)
    assert cleared and bar.selected is None


def test_dragging_the_ruler_scrubs_by_keyframes_then_exactly(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    moves: list[float] = []
    final: list[float] = []
    bar.seekRequested.connect(moves.append)
    bar.seekFinished.connect(final.append)
    _drag(bar, 100, 400, y=RULER_H / 2)
    assert len(moves) >= 3 and moves == sorted(moves)
    assert final == [pytest.approx(bar.time_at(400))]
    assert bar.selected is None  # линейка выбор не трогает


def test_dragging_the_right_edge_stretches_up_to_the_source_end(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    commits: list[tuple[int, float, float]] = []
    live: list[tuple[int, float, float]] = []
    bar.trimCommitted.connect(lambda i, a, b: commits.append((i, a, b)))
    bar.trimming.connect(lambda i, a, b: live.append((i, a, b)))
    edge = bar.block_rect(0).right()
    per_pixel = bar._seconds_per_pixel()
    _drag(bar, edge, edge + 5 / per_pixel)  # ещё на 5 секунд файла
    assert live and len(commits) == 1 and commits[0][:2] == (0, 0.0)
    assert commits[0][2] == pytest.approx(25.0, abs=0.5)
    far = bar.block_rect(0).right()
    _drag(bar, far, far + 5000)  # дальше конца файла не уйти
    assert commits[-1][2] == pytest.approx(60.0)


def test_dragging_the_left_edge_cannot_pass_the_right_one(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    commits: list[tuple[int, float, float]] = []
    bar.trimCommitted.connect(lambda i, a, b: commits.append((i, a, b)))
    edge = bar.block_rect(1).left()
    _drag(bar, edge, edge + 3000)
    index, start, stop = commits[-1]
    assert index == 1 and stop == 40.0 and 39.0 < start < 40.0  # остаётся минимум 0,1 с
    _drag(bar, bar.block_rect(1).left(), 0)
    assert commits[-1][1] == 0.0  # влево — до начала исходного файла


def test_live_edge_drag_moves_the_following_blocks(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    before = bar.block_rect(1).left()
    edge = bar.block_rect(0).right()
    _send(bar, QEvent.Type.MouseButtonPress, edge)
    _send(bar, QEvent.Type.MouseMove, edge + 80)
    assert bar.block_rect(1).left() > before + 40  # итог удлинился, сосед сдвинулся
    _send(bar, QEvent.Type.MouseButtonRelease, edge + 80)


def test_dragging_a_block_moves_it_with_an_insertion_target(qtbot: QtBot) -> None:
    blocks = [TimelineBlock(A, 60.0, i * 10.0, i * 10.0 + 10.0) for i in range(4)]
    bar = _bar(qtbot, blocks)
    moves: list[tuple[int, int]] = []
    bar.moveRequested.connect(lambda a, b: moves.append((a, b)))
    start = bar.block_rect(1).center().x()
    _send(bar, QEvent.Type.MouseButtonPress, start)
    _send(bar, QEvent.Type.MouseMove, start + 20)
    assert bar._drag == "move"
    end = bar.block_rect(3).right() - 4  # у самого конца: вставка после последнего
    _send(bar, QEvent.Type.MouseMove, end)
    assert bar._drop_slot == 4
    _send(bar, QEvent.Type.MouseButtonRelease, end)
    assert moves == [(1, 3)]  # после удаления из старого места блок встаёт последним


def test_dropping_back_on_the_same_place_does_nothing(qtbot: QtBot) -> None:
    blocks = [TimelineBlock(A, 60.0, i * 10.0, i * 10.0 + 10.0) for i in range(3)]
    bar = _bar(qtbot, blocks)
    moves: list[tuple[int, int]] = []
    bar.moveRequested.connect(lambda a, b: moves.append((a, b)))
    x = bar.block_rect(1).center().x()
    _drag(bar, x, x + 30)
    assert moves == []


def test_a_small_movement_is_a_click_not_a_drag(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    moves: list[tuple[int, int]] = []
    bar.moveRequested.connect(lambda a, b: moves.append((a, b)))
    x = bar.block_rect(0).center().x()
    _drag(bar, x, x + 2)
    assert moves == [] and bar.selected == 0


def test_zoom_wheel_and_auto_scroll(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    levels: list[float] = []
    bar.zoomChanged.connect(levels.append)
    bar.zoom_in()
    assert bar.zoom_level == pytest.approx(1.5) and levels[-1] == pytest.approx(1.5)
    event = QWheelEvent(
        QPointF(400, 60), QPointF(400, 60), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase,
        False,
    )  # fmt: skip
    bar.wheelEvent(event)
    assert bar.zoom_level > 1.5
    for _ in range(4):
        bar.zoom_in()
    bar.set_position(2.0)
    assert bar._visible(2.0)  # окно следует за позицией
    start = bar._view_start
    bar._press = ("body", 0, 100.0)
    bar._drag = "move"
    bar._move_x = bar.width() - 5
    bar._auto_scroll()
    assert bar._view_start > start  # у правого края полоса прокручивается
    bar._drag, bar._press = None, None
    bar.fit()
    assert bar.zoom_level == 1.0 and levels[-1] == 1.0


def test_precise_junction_and_thumbnails_are_drawn(qtbot: QtBot) -> None:
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    blocks = [
        TimelineBlock(A, 60.0, 0.0, 20.0),
        TimelineBlock(A, 60.0, 20.5, 40.0, precise=True, shift=0.5),
    ]
    bar = _bar(qtbot, blocks)
    bar.set_thumbs(A, [None, image, None, image])
    plain = bar.grab().toImage()
    bar.set_thumbnail(A, 0, image)
    assert bar.grab().toImage() != plain  # пришедшая миниатюра перерисовала полосу


def test_static_layer_is_cached_between_playhead_moves(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    bar.grab()
    cache = bar._cache
    assert cache is not None
    bar.set_position(5.0)
    bar.grab()
    assert bar._cache is cache  # линия позиции не пересоздаёт блоки и миниатюры
    bar.set_selected(1)
    bar.grab()
    assert bar._cache is not cache  # смена выбора пересобирает слой


def test_context_menu_reports_block_and_time(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    asked: list[object] = []
    bar.menuRequested.connect(lambda _pos, data: asked.append(data))
    x = int(bar.block_rect(1).center().x())
    bar.contextMenuEvent(
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(x, 60), bar.mapToGlobal(QPoint(x, 60))
        )
    )
    assert asked and asked[0][0] == 1  # type: ignore[index]
    assert bar.selected == 1
    bar.contextMenuEvent(
        QContextMenuEvent(
            QContextMenuEvent.Reason.Keyboard, QPoint(0, 0), bar.mapToGlobal(QPoint(0, 0))
        )
    )
    assert asked[-1] is None  # с клавиши — без точки


def test_range_label_formats_start_end_and_length() -> None:
    assert range_label(5.0, 25.5) == "0:05.0 – 0:25.5 · 0:20.5"


def test_edges_show_a_resize_cursor_on_hover(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    edge = bar.block_rect(0).right()
    bar._hover(edge, bar._track().center().y())
    assert bar.cursor().shape() == Qt.CursorShape.SizeHorCursor
    bar._hover(bar.block_rect(0).center().x(), bar._track().center().y())
    assert bar.cursor().shape() == Qt.CursorShape.OpenHandCursor


def test_shift_drag_marks_a_range_and_a_click_clears_it(qtbot: QtBot) -> None:
    bar = _bar(qtbot)
    marked: list[tuple[float, float]] = []
    bar.rangeMarked.connect(lambda a, b: marked.append((a, b)))
    y = bar._track().center().y()
    x0, x1 = bar.x_of(5.0), bar.x_of(15.0)
    shift = Qt.KeyboardModifier.ShiftModifier

    def event(kind: QEvent.Type, x: float) -> QMouseEvent:
        point = QPointF(x, y)
        button = LEFT if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        buttons = LEFT if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        return QMouseEvent(kind, point, bar.mapToGlobal(point), button, buttons, shift)

    bar.mousePressEvent(event(QEvent.Type.MouseButtonPress, x0))
    bar.mouseMoveEvent(event(QEvent.Type.MouseMove, x1))
    bar.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, x1))
    assert marked and marked[0] == (pytest.approx(5.0, abs=0.3), pytest.approx(15.0, abs=0.3))  # type: ignore[comparison-overlap]
    assert bar.marks is not None
    bar.grab()  # выделение рисуется
    _send(bar, QEvent.Type.MouseButtonPress, bar.block_rect(1).center().x())  # обычный щелчок
    _send(bar, QEvent.Type.MouseButtonRelease, bar.block_rect(1).center().x())
    assert bar.marks is None
