"""Холст редактора: показывает превью и рамки инструментов, передаёт им мышь."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from quickedit.core.geometry import Rect
from quickedit.ui.tools.base import Tool

MARGIN = 12.0
HANDLE_TOLERANCE_PX = 9.0  # зона захвата границы выделения на экране


class Canvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self.tool: Tool | None = None
        self.setMouseTracking(False)
        self.setMinimumSize(200, 150)

    # --- содержимое --------------------------------------------------------------------------

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def set_tool(self, tool: Tool | None) -> None:
        self.tool = tool
        self.setCursor(
            Qt.CursorShape.CrossCursor if tool is not None else Qt.CursorShape.ArrowCursor
        )
        self.update()

    # --- геометрия ---------------------------------------------------------------------------

    def image_scale(self) -> float:
        if self._image is None or self._image.isNull():
            return 1.0
        available_w = max(self.width() - 2 * MARGIN, 1.0)
        available_h = max(self.height() - 2 * MARGIN, 1.0)
        return min(available_w / self._image.width(), available_h / self._image.height())

    def image_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        scale = self.image_scale()
        width, height = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def to_image(self, pos: QPointF) -> tuple[float, float]:
        target = self.image_rect()
        scale = self.image_scale()
        return (pos.x() - target.left()) / scale, (pos.y() - target.top()) / scale

    def to_widget(self, x: float, y: float) -> QPointF:
        target = self.image_rect()
        scale = self.image_scale()
        return QPointF(target.left() + x * scale, target.top() + y * scale)

    def to_widget_rect(self, rect: Rect) -> QRectF:
        top_left = self.to_widget(rect.x, rect.y)
        scale = self.image_scale()
        return QRectF(top_left.x(), top_left.y(), rect.w * scale, rect.h * scale)

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(32, 32, 32))
        if self._image is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self._image)
        if self.tool is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(self.image_rect())
            self.tool.paint(painter, self)

    # --- мышь --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            x, y = self.to_image(event.position())
            self.tool.press(x, y, HANDLE_TOLERANCE_PX / self.image_scale())
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.tool.move(*self.to_image(event.position()))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            self.tool.release(*self.to_image(event.position()))
            self.update()
