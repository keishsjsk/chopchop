"""«Показать в папке»: открывает папку файла и, где можно, выделяет сам файл."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def reveal_command(path: Path) -> list[str] | None:
    """Команда проводника с выделением файла (только Windows); на других системах None."""
    if sys.platform == "win32":
        return ["explorer", f"/select,{path}"]
    return None


def reveal_in_folder(path: Path) -> None:
    command = reveal_command(path)
    if command is not None:
        subprocess.Popen(command)  # noqa: S603 - список аргументов, без shell
        return
    folder = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
