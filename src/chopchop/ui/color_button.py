"""Кнопка выбора цвета с образцом."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget

from chopchop.core.operations import Color
from chopchop.ui.theme import current, tokens


def hex_to_color(value: str) -> Color:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def color_to_hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


class ColorButton(QPushButton):
    colorChanged = Signal(tuple)

    def __init__(self, color: Color, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(tokens.MIN_HIT)
        self.clicked.connect(self._choose)
        self._refresh()

    @property
    def color(self) -> Color:
        return self._color

    def set_color(self, color: Color) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        border = current.palette().border_strong
        self.setStyleSheet(
            f"background-color: {color_to_hex(self._color)}; "
            f"border: {tokens.BORDER_WIDTH}px solid {border};"
        )

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self._color), self, self.tr("Цвет"))
        if chosen.isValid():
            self._color = (chosen.red(), chosen.green(), chosen.blue())
            self._refresh()
            self.colorChanged.emit(self._color)
