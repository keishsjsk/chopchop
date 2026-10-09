"""Скрытие области: сплошная заливка (по умолчанию), пикселизация или размытие."""

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QPainter

from chopchop.core.operations import Operation, Redact, RedactMode
from chopchop.ui.tools.base import RectSelectTool, ViewMapper

BLUR_RADIUS = 0.02  # доли длинной стороны кадра: превью и полный размер выглядят одинаково
PIXEL_BLOCK = 0.015


class RedactTool(RectSelectTool):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.mode: RedactMode = "fill"
        self._fill_overlay = False

    def set_overlay_fill(self, enabled: bool) -> None:
        """Заливку показывать закрашенным прямоугольником поверх кадра, без расчёта картинки."""
        self._fill_overlay = enabled
        self._sync_live()

    def _sync_live(self) -> None:
        self.live = not (self.mode == "fill" and self._fill_overlay)

    def set_mode(self, mode: RedactMode) -> None:
        self.mode = mode
        self._sync_live()
        self.changed.emit()

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        rect = self.selection.rect
        if rect is not None and not self.live:
            painter.fillRect(view.to_widget_rect(rect), QColor(*Redact(rect).color))
        super().paint(painter, view)

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
