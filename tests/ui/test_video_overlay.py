import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.video_overlay import VideoOverlay


def _overlay(qtbot: QtBot, frame: tuple[int, int] = (640, 360)) -> tuple[VideoOverlay, QWidget]:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    overlay = VideoOverlay(host, frame)
    host.show()
    return overlay, host


def test_follows_host_size(qtbot: QtBot) -> None:
    overlay, host = _overlay(qtbot)
    host.resize(500, 400)
    qtbot.waitUntil(lambda: overlay.size() == host.size(), timeout=2000)


def test_frame_is_letterboxed_in_the_center(qtbot: QtBot) -> None:
    overlay, _host = _overlay(qtbot)  # кадр 16:9 в окне 800x600
    rect = overlay.image_rect()
    assert (rect.width(), rect.height()) == pytest.approx((800, 450))
    assert (rect.x(), rect.y()) == pytest.approx((0, 75))


def test_coordinate_roundtrip(qtbot: QtBot) -> None:
    overlay, _host = _overlay(qtbot)
    point = overlay.to_widget(320, 180)
    assert (point.x(), point.y()) == pytest.approx((400, 300))
    assert overlay.to_frame(QPointF(point)) == pytest.approx((320, 180))
    box = overlay.to_widget_rect(Rect(64, 36, 128, 72))
    assert (box.x(), box.y(), box.width(), box.height()) == pytest.approx((80, 120, 160, 90))


def test_mouse_passes_through_without_tool(qtbot: QtBot) -> None:
    overlay, _host = _overlay(qtbot)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    tool = CropTool()
    overlay.set_tool(tool)
    assert not overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    overlay.set_tool(None)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_dragging_makes_selection_in_frame_coordinates(qtbot: QtBot) -> None:
    overlay, _host = _overlay(qtbot)
    tool = CropTool()
    tool.set_bounds(640, 360)
    overlay.set_tool(tool)
    start = overlay.to_widget(100, 80).toPoint()
    end = overlay.to_widget(400, 300).toPoint()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(overlay, end)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
    rect = tool.selection.rect
    assert rect is not None
    assert (rect.x, rect.y, rect.w, rect.h) == pytest.approx((100, 80, 300, 220), abs=2)


def test_paints_crop_and_selection_without_errors(qtbot: QtBot) -> None:
    overlay, host = _overlay(qtbot)
    overlay.set_crop(Rect(100, 50, 300, 200))
    overlay.set_rotation_note("Поворот")
    tool = CropTool()
    tool.set_bounds(640, 360)
    tool.selection.rect = Rect(10, 10, 100, 100)
    overlay.set_tool(tool)
    image = host.grab().toImage()
    assert not image.isNull()
