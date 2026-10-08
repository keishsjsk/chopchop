from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from quickedit.core.operations import Flip
from quickedit.player.libmpv import MpvUnavailableError
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


def test_video_without_libmpv_shows_warning(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise MpvUnavailableError("no libmpv")

    warnings: list[str] = []
    monkeypatch.setattr("quickedit.ui.main_window.load_mpv_module", unavailable)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, title, _text: warnings.append(title)
    )
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "movie.mkv")
    assert len(warnings) == 1
    assert window.video_page is None


def test_subtitle_file_is_not_opened_as_media(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "movie.srt")
    assert window.current_path is None


def _open_in_editor(qtbot: QtBot, tmp_path: Path) -> tuple[MainWindow, Path]:
    photos = tmp_path / "photos"
    photos.mkdir()
    first = _png(photos, "a.png", (40, 20))
    _png(photos, "b.png", (60, 30))
    window = _window(qtbot, tmp_path)
    window.open_file(first)
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    window.toggle_editor()
    qtbot.waitUntil(lambda: window.editor is not None, timeout=10000)
    return window, first


def test_editor_opens_and_returns_to_viewer(qtbot: QtBot, tmp_path: Path) -> None:
    window, first = _open_in_editor(qtbot, tmp_path)
    assert window._on_editor()
    assert "редактор" in window.windowTitle()
    window._escape()  # правок нет, поэтому выходим сразу
    assert window.editor is None
    assert window.current_path == first
    assert "(1/2)" in window.windowTitle()


def test_arrows_do_not_flip_photos_inside_editor(qtbot: QtBot, tmp_path: Path) -> None:
    window, first = _open_in_editor(qtbot, tmp_path)
    window._horizontal(1)
    assert window.current_path == first
    window._escape()


def test_editor_shortcuts_reach_editor(qtbot: QtBot, tmp_path: Path) -> None:
    window, _first = _open_in_editor(qtbot, tmp_path)
    assert window.editor is not None
    window._tool_slot("crop")()
    assert window.editor._active == "crop"
    window._tool_slot("crop")()  # повторное нажатие снимает инструмент
    assert window.editor._active is None
    window.editor.session.add_full(Flip(True))
    window._with_editor(lambda e: e.undo())
    assert not window.editor.session.history.can_undo
    window._escape()


def test_paste_image_from_clipboard_opens_editor(qtbot: QtBot, tmp_path: Path) -> None:
    clipboard_image = QImage(30, 20, QImage.Format.Format_RGB32)
    clipboard_image.fill(QColor("green"))
    QApplication.clipboard().setImage(clipboard_image)
    window = _window(qtbot, tmp_path)
    window.paste_image()
    qtbot.waitUntil(lambda: window.editor is not None, timeout=10000)
    assert window.editor is not None
    assert window.editor.session.source is None
    assert window.editor.session.output_size() == (30, 20)
    window._escape()
    assert window.editor is None


def test_paste_without_image_shows_message(qtbot: QtBot, tmp_path: Path) -> None:
    QApplication.clipboard().clear()
    window = _window(qtbot, tmp_path)
    window.paste_image()
    assert "буфере" in window.statusBar().currentMessage()
    assert window.editor is None
