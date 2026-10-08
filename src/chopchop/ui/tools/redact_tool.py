"""Скрытие области: сплошная заливка (по умолчанию), пикселизация или размытие."""

from PySide6.QtCore import QObject

from chopchop.core.operations import Operation, Redact, RedactMode
from chopchop.ui.tools.base import RectSelectTool

BLUR_RADIUS = 0.02  # доли длинной стороны кадра: превью и полный размер выглядят одинаково
PIXEL_BLOCK = 0.015


class RedactTool(RectSelectTool):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.mode: RedactMode = "fill"

    def set_mode(self, mode: RedactMode) -> None:
        self.mode = mode
        self.changed.emit()

    def pending_operation(self) -> Operation | None:
        rect = self.selection.rect
        if rect is None:
            return None
        if self.mode == "blur":
            strength = max(4.0, self.long_side * BLUR_RADIUS)
        elif self.mode == "pixelate":
            strength = max(6.0, self.long_side * PIXEL_BLOCK)
        else:
            strength = 0.0
        return Redact(rect, self.mode, strength)
