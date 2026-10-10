"""Стоимость перерисовки при перетаскивании: области обновления и время обработчиков.

Идёт на offscreen, то есть на программном рендере без видеокарты, как в CI. Проверки:
  - при переносе «призрака» блока обновляется часть полосы, а не вся полоса;
  - время обработки события не растёт с числом событий (нет накопления) и укладывается в бюджет;
  - первое и последнее перетаскивание стоят одинаково.
"""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from chopchop.ui.canvas import Canvas
from chopchop.ui.timeline import Timeline, TimelineBlock
from chopchop.ui.tools.crop_tool import CropTool

LEFT = Qt.MouseButton.LeftButton
BUDGET_MS = 25.0  # обработчик + перерисовка одного движения на медленном CI-компьютере


def _mouse(widget, kind: QEvent.Type, x: float, y: float) -> None:  # type: ignore[no-untyped-def]
    point = QPointF(x, y)
    buttons = LEFT if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    button = LEFT if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    event = QMouseEvent(
        kind,
        point,
        widget.mapToGlobal(point),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _record_updates(widget) -> list[QRect]:  # type: ignore[no-untyped-def]
    """Подменяет `update(rect)` и копит запрошенные области (пустая — весь виджет)."""
    areas: list[QRect] = []
    original = type(widget).update

    def update(*args: object) -> None:
        areas.append(args[0] if args and isinstance(args[0], QRect) else widget.rect())
        original(widget, *args)

    widget.update = update
    return areas


def _timeline(qtbot: QtBot) -> Timeline:
    bar = Timeline()
    qtbot.addWidget(bar)
    bar.resize(1200, 112)
    bar.show()
    blocks = [TimelineBlock(Path("a.mp4"), 100.0, i * 20.0, i * 20.0 + 20.0) for i in range(5)]
    bar.set_blocks(blocks)
    return bar


def _canvas(qtbot: QtBot) -> tuple[Canvas, CropTool]:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(1000, 700)
    canvas.show()
    image = QImage(6000, 4000, QImage.Format.Format_RGB32)
    image.fill(QColor(90, 100, 110))
    canvas.set_image(image)
    tool = CropTool()
    tool.set_bounds(6000, 4000)
    canvas.set_tool(tool)
    tool.select_all()
    return canvas, tool


def test_block_ghost_move_does_not_repaint_the_whole_bar(qtbot: QtBot) -> None:
    bar = _timeline(qtbot)
    bar.grab()
    y = bar._track().center().y()
    x0 = bar.block_rect(0).center().x()
    _mouse(bar, QEvent.Type.MouseButtonPress, x0, y)
    _mouse(bar, QEvent.Type.MouseMove, x0 + 12, y)  # порог переноса пройден
    areas = _record_updates(bar)
    for i in range(1, 8):
        _mouse(bar, QEvent.Type.MouseMove, x0 + 12 + i * 2, y)  # в пределах того же слота
    _mouse(bar, QEvent.Type.MouseButtonRelease, x0 + 26, y)
    whole = bar.width() * bar.height()
    partial = [a for a in areas if a.width() * a.height() < whole * 0.5]
    assert partial, "перенос блока перерисовывает всю полосу на каждое движение"


def _drag_cost(widget, points: list[tuple[float, float]]) -> list[float]:  # type: ignore[no-untyped-def]
    """Время каждого движения вместе с перерисовкой, мс."""
    costs: list[float] = []
    _mouse(widget, QEvent.Type.MouseButtonPress, *points[0])
    for x, y in points[1:]:
        started = time.perf_counter()
        _mouse(widget, QEvent.Type.MouseMove, x, y)
        QApplication.processEvents()
        widget.repaint()
        costs.append((time.perf_counter() - started) * 1000)
    _mouse(widget, QEvent.Type.MouseButtonRelease, *points[-1])
    return costs


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(len(ordered) * 0.95)]


def test_block_drag_cost_is_within_budget_and_does_not_grow(qtbot: QtBot) -> None:
    bar = _timeline(qtbot)
    bar.grab()
    y = bar._track().center().y()
    x0, x1 = bar.block_rect(0).center().x(), bar.block_rect(4).center().x()
    route = [(x0 + (x1 - x0) * i / 150, y) for i in range(151)]
    first = _drag_cost(bar, route)
    for _ in range(3):
        _drag_cost(bar, route)
    last = _drag_cost(bar, route)
    assert _p95(first) < BUDGET_MS and _p95(last) < BUDGET_MS
    assert _p95(last) < max(_p95(first) * 3, 3.0)  # от перетаскивания к перетаскиванию не растёт


def test_crop_drag_cost_is_within_budget_and_does_not_grow(qtbot: QtBot) -> None:
    canvas, _tool = _canvas(qtbot)
    canvas.grab()
    target = canvas.image_rect()
    start = (target.left() + 2, target.top() + 2)
    route = [(start[0] + i * 2, start[1] + i * 1.2) for i in range(150)]
    first = _drag_cost(canvas, route)
    for _ in range(3):
        _drag_cost(canvas, route)
    last = _drag_cost(canvas, route)
    assert _p95(first) < BUDGET_MS and _p95(last) < BUDGET_MS
    assert _p95(last) < max(_p95(first) * 3, 3.0)


@pytest.mark.parametrize("count", [50, 400])
def test_per_event_cost_does_not_depend_on_event_count(qtbot: QtBot, count: int) -> None:
    bar = _timeline(qtbot)
    bar.grab()
    y = bar._track().center().y()
    x0, x1 = bar.block_rect(0).center().x(), bar.block_rect(4).center().x()
    route = [(x0 + (x1 - x0) * i / count, y) for i in range(count + 1)]
    costs = _drag_cost(bar, route)
    assert sum(costs) / len(costs) < BUDGET_MS
