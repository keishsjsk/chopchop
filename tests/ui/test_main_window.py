from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from quickedit.ui.main_window import MainWindow


def _window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    return window


def test_window_opens_with_drop_zone(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.show()
    assert window.current_path is None
    assert "ffmpeg" in window.statusBar().currentMessage()


def test_open_supported_file(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "photo.jpg")
    assert window.current_path == tmp_path / "photo.jpg"
    assert "photo.jpg" in window.windowTitle()


def test_open_unsupported_file_is_ignored(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    window.open_file(tmp_path / "notes.txt")
    assert window.current_path is None
