"""Создание QApplication и главного окна."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from quickedit.services.settings import default_settings
from quickedit.ui.main_window import MainWindow


def run(initial: Path | None = None) -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("QuickEdit")
    window = MainWindow(default_settings())
    window.show()
    if initial is not None:
        window.open_file(initial)
    return app.exec()
