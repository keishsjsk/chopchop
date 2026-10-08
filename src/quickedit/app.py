"""Создание QApplication и главного окна."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from quickedit import __version__
from quickedit.services.paths import resource_dir
from quickedit.services.settings import default_settings
from quickedit.services.temp_files import cleanup_stale
from quickedit.ui.main_window import MainWindow

APP_ID = "QuickEdit.QuickEdit"


def _set_windows_app_id() -> None:
    """Свой идентификатор приложения: значок в панели задач не склеивается с Python."""
    if sys.platform != "win32":
        return
    import contextlib
    import ctypes

    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def run(initial: Path | None = None) -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("QuickEdit")
    app.setApplicationVersion(__version__)
    icon = resource_dir() / "icons" / "quickedit.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    cleanup_stale()
    window = MainWindow(default_settings())
    window.show()
    if initial is not None:
        window.open_file(initial)
    return app.exec()
