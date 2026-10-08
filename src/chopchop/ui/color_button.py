"""Кнопка выбора цвета с образцом."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget

from chopchop.core.operations import Color


class ColorButton(QPushButton):
    colorChanged = Signal(tuple)

    def __init__(self, color: Color, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(26)
        self.clicked.connect(self._choose)
        self._refresh()

    @property
    def color(self) -> Color:
        return self._color

    def set_color(self, color: Color) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        r, g, b = self._color
        self.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #888;")

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self._color), self, self.tr("Цвет"))
        if chosen.isValid():
            self._color = (chosen.red(), chosen.green(), chosen.blue())
            self._refresh()
            self.colorChanged.emit(self._color)
