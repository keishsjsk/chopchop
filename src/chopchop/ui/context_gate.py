"""Когда контекстное меню открывать нельзя: пока идёт перетаскивание (рамка, ручка, штрих)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


def menu_allowed() -> bool:
    """Нажата левая кнопка мыши — значит, что-то тянут; меню в этот момент не нужно."""
    return not (QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)
