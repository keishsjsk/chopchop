"""Ступенчатые рамки и жёсткие тени через QPainter: «пиксельная» форма без размытия.

Скругление здесь — ступенька из квадратиков размера `step`, а тень — тот же контур, сдвинутый
без размытия. Всё рисуется без сглаживания, поэтому края остаются ровными.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import QFrame, QWidget

from chopchop.ui.theme.tokens import (
    BORDER_WIDTH,
    LIGHT,
    PIXEL_STEP,
    SHADOW_OFFSET,
    Palette,
)


def stepped_polygon(rect: QRectF, step: float = PIXEL_STEP, levels: int = 1) -> QPolygonF:
    """Прямоугольник со срезанными ступенькой углами.

    levels=1 — срезан один квадрат step в каждом углу; levels=2 — «лесенка» из двух ступеней
    (два квадрата по верхней стороне и один по боковой), угол выглядит круглее.
    """
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    s = step
    if levels <= 1:
        points = [
            (left + s, top),
            (right - s, top),
            (right, top + s),
            (right, bottom - s),
            (right - s, bottom),
            (left + s, bottom),
            (left, bottom - s),
            (left, top + s),
        ]
    else:
        points = [
            (left + 2 * s, top),
            (right - 2 * s, top),
            (right - 2 * s, top + s),
            (right - s, top + s),
            (right - s, top + 2 * s),
            (right, top + 2 * s),
            (right, bottom - 2 * s),
            (right - s, bottom - 2 * s),
            (right - s, bottom - s),
            (right - 2 * s, bottom - s),
            (right - 2 * s, bottom),
            (left + 2 * s, bottom),
            (left + 2 * s, bottom - s),
            (left + s, bottom - s),
            (left + s, bottom - 2 * s),
            (left, bottom - 2 * s),
            (left, top + 2 * s),
            (left + s, top + 2 * s),
            (left + s, top + s),
            (left + 2 * s, top + s),
        ]
    return QPolygonF([QPointF(x, y) for x, y in points])


def stepped_path(rect: QRectF, step: float = PIXEL_STEP, levels: int = 1) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(stepped_polygon(rect, step, levels))
    path.closeSubpath()
    return path


def paint_frame(
    painter: QPainter,
    rect: QRectF,
    *,
    fill: str,
    border: str,
    shadow: str | None = None,
    step: float = PIXEL_STEP,
    levels: int = 1,
    border_width: float = BORDER_WIDTH,
    shadow_offset: float = SHADOW_OFFSET,
) -> None:
    """Рамка со ступенчатыми углами, заливкой и необязательной жёсткой тенью.

    rect — внешний прямоугольник вместе с рамкой; тень выходит за него вправо и вниз.
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    if shadow is not None:
        painter.setBrush(QBrush(QColor(shadow)))
        painter.drawPath(stepped_path(rect.translated(shadow_offset, shadow_offset), step, levels))
    painter.setBrush(QBrush(QColor(border)))
    painter.drawPath(stepped_path(rect, step, levels))
    inner = rect.adjusted(border_width, border_width, -border_width, -border_width)
    if inner.width() > 0 and inner.height() > 0:
        painter.setBrush(QBrush(QColor(fill)))
        painter.drawPath(stepped_path(inner, step, max(levels - 1, 1)))
    painter.restore()


class PixelFrame(QFrame):
    """Панель со ступенчатой рамкой в цветах темы (карточки, плавающие панели, подсказки)."""

    def __init__(
        self,
        palette: Palette = LIGHT,
        *,
        raised: bool = False,
        shadow: bool = True,
        levels: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette_tokens = palette
        self._raised = raised
        self._shadow = shadow
        self._levels = levels
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_tokens(self, palette: Palette) -> None:
        """Смена темы на лету: перерисовывается только эта панель."""
        self._palette_tokens = palette
        self.update()

    def content_margins(self) -> int:
        """Отступ внутрь, чтобы содержимое не заходило на рамку и тень."""
        return int(BORDER_WIDTH + (SHADOW_OFFSET if self._shadow else 0))

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        p = self._palette_tokens
        reserve = SHADOW_OFFSET if self._shadow else 0
        rect = QRectF(0, 0, self.width() - reserve, self.height() - reserve)
        paint_frame(
            painter,
            rect,
            fill=p.surface_raised if self._raised else p.surface,
            border=p.border_strong,
            shadow=p.shadow if self._shadow else None,
            levels=self._levels,
        )
