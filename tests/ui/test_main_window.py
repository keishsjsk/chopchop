from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from quickedit.ui.main_window import MainWindow


def _window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    return window


def _png(folder: Path, name: str, size: tuple[int, int]) -> Path:
    path = folder / name
    Image.new("RGB", size, "red").save(path)
    return path


def test_window_opens_with_drop_zone(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    assert window.current_path is None
    assert "ffmpeg" in window.statusBar().currentMessage()


def test_open_image_shows_viewer(qtbot: QtBot, tmp_path: Path) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    path = _png(photos, "photo.png", (64, 32))
    window = _window(qtbot, tmp_path)
    window.open_file(path)
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    assert window.current_path == path
    assert "photo.png (1/1)" in window.windowTitle()
    assert "64×32" in window.statusBar().currentMessage()


def test_arrows_flip_through_folder(qtbot: QtBot, tmp_path: Path) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    first = _png(photos, "a.png", (10, 10))
    second = _png(photos, "b.png", (20, 20))
    window = _window(qtbot, tmp_path)
    window.open_file(first)
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)

    window.step(1)
    qtbot.waitUntil(lambda: window.current_path == second, timeout=5000)
    qtbot.waitUntil(lambda: "20×20" in window.statusBar().currentMessage(), timeout=5000)
    assert "(2/2)" in window.windowTitle()

    window.step(1)  # по кругу обратно к первому
    assert window.current_path == first


def test_broken_image_reports_error(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "missing.jpg")
    qtbot.waitUntil(lambda: "Не удалось" in window.statusBar().currentMessage(), timeout=5000)


def test_open_unsupported_file_is_ignored(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "notes.txt")
    assert window.current_path is None


def test_fullscreen_toggle(qtbot: QtBot, tmp_path: Path) -> None:
    path = _png(tmp_path, "a.png", (10, 10))
    window = _window(qtbot, tmp_path)
    window.toggle_fullscreen()  # на стартовом экране ничего не происходит
    assert not window.isFullScreen()
    window.open_file(path)
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    window.toggle_fullscreen()
    assert window.isFullScreen()
    window.exit_fullscreen()
    assert not window.isFullScreen()
