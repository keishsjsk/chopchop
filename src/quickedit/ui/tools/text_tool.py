"""Текст на фото: клик задаёт положение, Enter — применить."""

from PySide6.QtCore import QObject

from quickedit.core.operations import Color, Operation, Text
from quickedit.ui.tools.base import Tool


class TextTool(Tool):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.text = ""
        self.size_percent = 6.0  # высота букв в процентах от высоты кадра
        self.color: Color = (255, 255, 255)
        self._position: tuple[float, float] | None = None

    def press(self, x: float, y: float, tolerance: float) -> None:
        self._position = (x, y)
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        if self._position is not None:
            self._position = (x, y)
            self.changed.emit()

    def set_options(self, text: str, size_percent: float, color: Color) -> None:
        self.text, self.size_percent, self.color = text, size_percent, color
        self.changed.emit()

    def pending_operation(self) -> Operation | None:
        if not self.text.strip():
            return None
        # без клика текст появляется в левом верхнем углу, чтобы его было видно сразу
        x, y = self._position or (self.bounds[0] * 0.05, self.bounds[1] * 0.05)
        return Text(self.text, x, y, self.size_percent / 100 * self.bounds[1], self.color)

    def reset(self) -> None:
        self._position = None
        self.changed.emit()
