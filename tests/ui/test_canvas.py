import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot

from quickedit.core.geometry import Rect
from quickedit.ui.canvas import Canvas
from quickedit.ui.tools.crop_tool import CropTool


def _canvas(qtbot: QtBot) -> Canvas:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(424, 224)  # поле 12 пикселей с каждой стороны
    canvas.show()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    canvas.set_image(image)
    return canvas


def test_image_is_fitted_and_centered(qtbot: QtBot) -> None:
    canvas = _canvas(qtbot)
    assert canvas.image_scale() == pytest.approx(2.0)
    rect = canvas.image_rect()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == pytest.approx((12, 12, 400, 200))


def test_coordinate_roundtrip(qtbot: QtBot) -> None:
    canvas = _canvas(qtbot)
    widget_point = canvas.to_widget(50, 25)
    assert canvas.to_image(QPointF(widget_point)) == pytest.approx((50, 25))
    assert canvas.to_image(QPointF(12, 12)) == pytest.approx((0, 0))
    box = canvas.to_widget_rect(Rect(10, 10, 20, 20))
    assert (box.x(), box.y(), box.width()) == pytest.approx((32, 32, 40))


def test_mouse_drives_active_tool(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    canvas = _canvas(qtbot)
    tool = CropTool()
    tool.set_bounds(200, 100)
    canvas.set_tool(tool)
    start = canvas.to_widget(20, 20).toPoint()
    end = canvas.to_widget(120, 70).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    rect = tool.selection.rect
    assert rect is not None
    assert (rect.x, rect.y, rect.w, rect.h) == pytest.approx((20, 20, 100, 50), abs=1)
