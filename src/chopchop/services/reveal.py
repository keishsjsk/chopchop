"""«Показать в папке»: открывает папку файла и, где можно, выделяет сам файл.

Windows: `explorer /select,<путь>` одним списком аргументов. Linux: вызов D-Bus
`org.freedesktop.FileManager1.ShowItems` (его понимают Nautilus, Dolphin, Nemo, Thunar), а если
файлового менеджера с таким интерфейсом нет, открывается родительская папка. Оболочка (shell)
нигде не участвует, имя файла передаётся как данные.
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PySide6.QtGui import QDesktopServices

SERVICE = "org.freedesktop.FileManager1"
OBJECT = "/org/freedesktop/FileManager1"
INTERFACE = "org.freedesktop.FileManager1"
METHOD = "ShowItems"
DBUS_TIMEOUT_MS = 2000


def reveal_command(path: Path) -> list[str] | None:
    """Команда проводника с выделением файла (только Windows); на других системах None."""
    if sys.platform == "win32":
        return ["explorer", f"/select,{path}"]
    return None


def show_items_message(path: Path) -> QDBusMessage:
    """Вызов ShowItems: адрес файла как file://-URI и пустой идентификатор запуска."""
    message = QDBusMessage.createMethodCall(SERVICE, OBJECT, INTERFACE, METHOD)
    message.setArguments([[QUrl.fromLocalFile(str(path)).toString()], ""])
    return message


def _reveal_with_dbus(path: Path) -> bool:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    reply = bus.call(show_items_message(path), QDBus.CallMode.Block, DBUS_TIMEOUT_MS)
    return reply.type() != QDBusMessage.MessageType.ErrorMessage


def _open_folder(path: Path) -> None:
    folder = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def reveal_in_folder(path: Path) -> None:
    command = reveal_command(path)
    if command is not None:
        subprocess.Popen(command)  # noqa: S603 - список аргументов, без shell
        return
    if sys.platform.startswith("linux") and _reveal_with_dbus(path):
        return
    _open_folder(path)
