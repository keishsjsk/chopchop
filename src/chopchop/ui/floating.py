"""Плавающая панель: ступенчатая рамка с жёсткой тенью поверх содержимого, плавное появление."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLayout, QVBoxLayout, QWidget

from chopchop.ui import anim
from chopchop.ui.theme import current, tokens
from chopchop.ui.theme.pixel import paint_frame


class FloatingPanel(QWidget):
    """Панель с рамкой в цветах темы. Тень занимает правый нижний край, поэтому отступы больше."""

    def __init__(self, parent: QWidget | None = None, *, shadow: bool = True) -> None:
        super().__init__(parent)
        self._shadow = shadow
        self._fader = anim.Fader(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    @property
    def reserve(self) -> int:
        return tokens.SHADOW_OFFSET if self._shadow else 0

    def set_content(self, layout: QLayout, padding: int = tokens.SPACE_2) -> None:
        """Раскладка внутри рамки: отступ от рамки и место под тень справа и снизу."""
        edge = tokens.BORDER_WIDTH + padding
        layout.setContentsMargins(edge, edge, edge + self.reserve, edge + self.reserve)
        self.setLayout(layout)

    def horizontal(self, padding: int = tokens.SPACE_2) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(tokens.SPACE_2)
        self.set_content(layout, padding)
        return layout

    def vertical(self, padding: int = tokens.SPACE_2) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(tokens.SPACE_2)
        self.set_content(layout, padding)
        return layout

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        rect = QRectF(0, 0, self.width() - self.reserve, self.height() - self.reserve)
        paint_frame(
            painter,
            rect,
            fill=p.surface_raised,
            border=p.border_strong,
            shadow=p.shadow if self._shadow else None,
            levels=1,
        )

    # --- плавное появление -------------------------------------------------------------------

    @property
    def opacity(self) -> float:
        return self._fader.opacity

    def appear(self) -> None:
        if self.isVisible() and self._fader.opacity >= 1.0:
            return
        if not self.isVisible():
            self._fader.fade_to(0.0, 0)
            self.show()
        self._fader.fade_to(1.0, tokens.PANEL_MS)

    def disappear(self) -> None:
        if not self.isVisible():
            return
        self._fader.fade_to(0.0, tokens.PANEL_MS, self.hide)
