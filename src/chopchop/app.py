"""Создание QApplication и главного окна."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from chopchop import __version__
from chopchop.services.paths import resource_dir
from chopchop.services.settings import default_settings
from chopchop.services.temp_files import cleanup_stale
from chopchop.ui.main_window import MainWindow

APP_ID = "CHOPCHOP.CHOPCHOP"


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
    app.setApplicationName("CHOPCHOP")
    app.setApplicationVersion(__version__)
    icon = resource_dir() / "icons" / "chopchop.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    cleanup_stale()
    window = MainWindow(default_settings())
    window.show()
    if initial is not None:
        window.open_file(initial)
    return app.exec()
