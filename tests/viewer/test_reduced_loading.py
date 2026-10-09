"""Быстрый первый показ: сначала уменьшенная копия, затем полная без прыжка масштаба."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot

from chopchop.ui.main_window import MainWindow
from chopchop.viewer.image_loader import load_reduced
from chopchop.viewer.image_viewer import ImageViewer
from chopchop.viewer.prefetch import ImageCache


def _jpeg(path: Path, size: tuple[int, int] = (3000, 2000)) -> Path:
    Image.new("RGB", size, (20, 120, 220)).save(path, quality=85)
    return path


def test_reduced_copy_is_smaller_and_keeps_proportions(tmp_path: Path) -> None:
    image = load_reduced(_jpeg(tmp_path / "a.jpg"), 1000)
    assert image is not None
    assert max(image.width(), image.height()) == 1000
    assert abs(image.width() / image.height() - 1.5) < 0.01


def test_nothing_to_reduce_for_small_pictures_or_formats_without_scaling(tmp_path: Path) -> None:
    assert load_reduced(_jpeg(tmp_path / "small.jpg", (800, 600)), 1000) is None
    png = tmp_path / "a.png"
    Image.new("RGB", (3000, 2000)).save(png)
    assert load_reduced(png, 1000) is None  # PNG целиком, быстрого пути нет


def test_reduced_copy_respects_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (3000, 2000), (1, 2, 3)).save(path, exif=exif)
    image = load_reduced(path, 1000)
    assert image is not None
    assert image.height() > image.width()


def test_cache_announces_reduced_before_full(qtbot: QtBot, tmp_path: Path) -> None:
    cache = ImageCache()
    path = _jpeg(tmp_path / "a.jpg")
    order: list[str] = []
    cache.reducedLoaded.connect(lambda _p, _i: order.append("reduced"))
    cache.loaded.connect(lambda _p, _i: order.append("full"))
    cache.request_reduced(path, 1000)
    cache.request(path)
    qtbot.waitUntil(lambda: "full" in order, timeout=10000)
    assert "reduced" in order
    cache.wait()


def test_replacing_keeps_what_the_user_sees(qtbot: QtBot) -> None:
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(400, 300)
    viewer.show()
    small = QImage(500, 400, QImage.Format.Format_RGB32)
    small.fill(QColor("red"))
    viewer.set_image(small)
    viewer.actual_size()
    viewer.zoom_by(2.0)  # пользователь приблизил уменьшенную копию
    shown = viewer.zoom() * 500
    full = QImage(2000, 1600, QImage.Format.Format_RGB32)
    full.fill(QColor("red"))
    viewer.replace_image(full)
    assert abs(viewer.zoom() * 2000 - shown) < 1  # ширина на экране не изменилась


def test_replacing_in_fit_mode_refits(qtbot: QtBot) -> None:
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(400, 300)
    viewer.show()
    small = QImage(1000, 800, QImage.Format.Format_RGB32)
    small.fill(QColor("red"))
    viewer.set_image(small)
    full = QImage(4000, 3200, QImage.Format.Format_RGB32)
    full.fill(QColor("red"))
    viewer.replace_image(full)
    assert viewer.zoom() * 4000 <= 400 + 1


def test_window_shows_reduced_copy_first_then_full(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.resize(500, 400)
    window.show()
    path = _jpeg(tmp_path / "big.jpg", (4000, 3000))
    sizes: list[int] = []
    original = window.viewer.set_image

    def spy(image: QImage) -> None:
        sizes.append(image.width())
        original(image)

    window.viewer.set_image = spy  # type: ignore[method-assign]
    window.open_file(path)
    qtbot.waitUntil(lambda: window._cache.get(path) is not None, timeout=10000)
    qtbot.wait(50)
    assert sizes[-1] == 4000  # в конце на экране полная картинка
    assert window.viewer.has_image()
    window._cache.wait()
