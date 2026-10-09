"""Холст не пересчитывает картинку при каждой перерисовке; штрих рисуется поверх кадра."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from chopchop.core.operations import Stroke
from chopchop.editor.session import EditSession
from chopchop.services import profiling
from chopchop.ui.canvas import Canvas
from chopchop.ui.editor_page import EditorPage
from chopchop.ui.tools.draw_tool import DrawTool


@pytest.fixture
def profile_on() -> Iterator[None]:
    profiling.set_enabled(True)
    profiling.clear()
    yield
    profiling.set_enabled(False)
    profiling.clear()


def _canvas(qtbot: QtBot, size: tuple[int, int] = (200, 100)) -> Canvas:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(424, 224)
    canvas.show()
    qtbot.waitExposed(canvas)
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(QColor(30, 60, 90))
    canvas.set_image(image)
    return canvas


def _scales() -> int:
    return sum(1 for name, _ in profiling.records() if name == "canvas.scale")


def test_repainting_reuses_the_scaled_picture(qtbot: QtBot, profile_on: None) -> None:
    canvas = _canvas(qtbot)
    canvas.grab()
    assert _scales() == 1
    for _ in range(5):
        canvas.grab()
    canvas.update()
    canvas.grab()
    assert _scales() == 1  # размер и картинка те же: масштабирование не повторялось


def test_resize_and_new_image_rescale_once(qtbot: QtBot, profile_on: None) -> None:
    canvas = _canvas(qtbot)
    canvas.grab()
    canvas.resize(500, 300)
    canvas.grab()
    assert _scales() == 2
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    canvas.set_image(image)
    canvas.grab()
    assert _scales() == 3


def test_pixels_on_screen_match_the_image(qtbot: QtBot) -> None:
    canvas = _canvas(qtbot)
    grabbed = canvas.grab().toImage()
    center = grabbed.pixelColor(212, 112)
    assert (center.red(), center.green(), center.blue()) == pytest.approx((30, 60, 90), abs=2)
    corner = grabbed.pixelColor(2, 2)  # поле вокруг картинки закрашено фоном холста
    assert (corner.red(), corner.green(), corner.blue()) == (32, 32, 32)


def _draw_page(qtbot: QtBot, tmp_path: Path) -> tuple[EditorPage, DrawTool]:
    path = tmp_path / "p.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(path)
    session = EditSession(path)
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    page = EditorPage(session)
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()
    qtbot.waitExposed(page)
    page.select_tool("draw")
    page._shape.setCurrentIndex(page._shape.findData("pen"))
    tool = page.tools["draw"]
    assert isinstance(tool, DrawTool)
    return page, tool


def test_stroke_is_visible_on_the_canvas_while_the_button_is_held(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page, tool = _draw_page(qtbot, tmp_path)
    canvas = page.canvas
    start = canvas.to_widget(20, 50).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 12):
        QTest.mouseMove(canvas, canvas.to_widget(20 + step * 10, 50).toPoint())
    assert len(page.session.history) == 0  # кнопка зажата, в историю ничего не ушло
    middle = _pixel(canvas, 70, 50)
    assert middle.red() > 200 and middle.green() < 80  # красная линия уже видна
    outside = _pixel(canvas, 70, 5)
    assert outside.green() > 200
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 200, start.y()))
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=5000)
    (op,) = page.session.history.operations
    assert isinstance(op, Stroke)
    assert len(op.points) == 2  # прямая линия сведена к концам: меньше точек, та же форма
    after = _pixel(canvas, 70, 50)
    assert after.green() < 200  # теперь линия в самой картинке (тонкая, после сглаживания светлее)
    page.session.wait()


def _pixel(canvas: Canvas, x: float, y: float) -> QColor:
    """Цвет на экране в точке картинки (x, y); снимок хранится в пикселях устройства."""
    shot = canvas.grab().toImage()
    point = canvas.to_widget(x, y)
    ratio = shot.devicePixelRatio()
    return shot.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


def test_freehand_mouse_move_reports_only_the_changed_area(qtbot: QtBot, tmp_path: Path) -> None:
    _page, tool = _draw_page(qtbot, tmp_path)
    tool.press(20, 20, 4.0)
    tool.move(30, 25)
    tool.move(40, 30)
    dirty = tool.dirty_rect()
    assert dirty is not None
    assert dirty.w < 60 and dirty.h < 40  # только последний отрезок, а не весь штрих
    tool.release(40, 30)
    assert tool.dirty_rect() is None  # после упрощения штриха перерисовывается всё
    _page.session.wait()


def test_frozen_stroke_stays_until_the_new_picture_is_ready(qtbot: QtBot, tmp_path: Path) -> None:
    _page, tool = _draw_page(qtbot, tmp_path)
    tool.press(20, 20, 4.0)
    tool.move(100, 60)
    tool.move(150, 20)
    tool.commit()
    assert tool.pending_operation() is None  # дважды не применится
    tool.end_commit()
    assert tool._points == []
    _page.session.wait()
