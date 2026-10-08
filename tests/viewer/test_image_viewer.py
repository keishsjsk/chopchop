import pytest
from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot

from quickedit.viewer.image_viewer import ImageViewer


def _viewer(qtbot: QtBot, width: int, height: int) -> ImageViewer:
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(200, 100)
    viewer.show()
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    viewer.set_image(image)
    return viewer


def test_large_image_is_fitted_down(qtbot: QtBot) -> None:
    viewer = _viewer(qtbot, 2000, 1000)
    assert viewer.has_image()
    assert viewer.zoom() < 0.2


def test_small_image_is_not_upscaled(qtbot: QtBot) -> None:
    viewer = _viewer(qtbot, 20, 10)
    assert viewer.zoom() == pytest.approx(1.0)


def test_zoom_and_reset(qtbot: QtBot) -> None:
    viewer = _viewer(qtbot, 2000, 1000)
    viewer.actual_size()
    assert viewer.zoom() == pytest.approx(1.0)
    viewer.zoom_by(2)
    assert viewer.zoom() == pytest.approx(2.0)
    viewer.fit_to_window()
    assert viewer.zoom() < 0.2


def test_zoom_is_clamped(qtbot: QtBot) -> None:
    viewer = _viewer(qtbot, 20, 10)
    viewer.zoom_by(1e6)
    assert viewer.zoom() == pytest.approx(32.0)
    viewer.zoom_by(1e-9)
    assert viewer.zoom() == pytest.approx(0.05)
