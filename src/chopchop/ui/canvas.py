"""Холст редактора: показывает превью и рамки инструментов, передаёт им мышь.

Картинка один раз масштабируется до размера на экране и хранится как QPixmap: перерисовка при
движении мыши — это копирование готовых пикселей, а не пересчёт 2-мегапиксельного кадра.
"""

import contextlib

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from chopchop.core.geometry import Rect
from chopchop.services.profiling import stage
from chopchop.ui.tools.base import Tool

MARGIN = 12.0
HANDLE_TOLERANCE_PX = 9.0  # зона захвата границы выделения на экране
BACKGROUND = QColor(32, 32, 32)


class Canvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._pixmap: QPixmap | None = None
        self._pixmap_key: tuple[int, int, int, float] | None = None
        self.tool: Tool | None = None
        self.setMouseTracking(False)
        self.setMinimumSize(200, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)  # фон закрашиваем сами

    # --- содержимое --------------------------------------------------------------------------

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._pixmap = None
        self.update()

    def set_tool(self, tool: Tool | None) -> None:
        if self.tool is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self.tool.changed.disconnect(self._on_tool_changed)
        self.tool = tool
        if tool is not None:
            tool.changed.connect(self._on_tool_changed)
        self.setCursor(
            Qt.CursorShape.CrossCursor if tool is not None else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def _on_tool_changed(self) -> None:
        dirty = self.tool.dirty_rect() if self.tool is not None else None
        if dirty is None:
            self.update()
        else:
            self.update_image_rect(dirty)

    def update_image_rect(self, rect: Rect) -> None:
        """Перерисовать только область, заданную в пикселях картинки."""
        area = self.to_widget_rect(rect).toAlignedRect().adjusted(-2, -2, 2, 2)
        self.update(area.intersected(self.rect()))

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

    def _scaled_pixmap(self) -> QPixmap | None:
        """Картинка нужного размера в пикселях экрана; пересобирается только при изменении."""
        image = self._image
        if image is None or image.isNull():
            return None
        ratio = self.devicePixelRatioF()
        target = self.image_rect()
        size = QSize(max(round(target.width() * ratio), 1), max(round(target.height() * ratio), 1))
        key = (image.cacheKey(), size.width(), size.height(), ratio)
        if self._pixmap is None or key != self._pixmap_key:
            with stage("canvas.scale"):
                scaled = (
                    image
                    if size == image.size()
                    else image.scaled(
                        size,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._pixmap = QPixmap.fromImage(scaled)
                self._pixmap.setDevicePixelRatio(ratio)
            self._pixmap_key = key
        return self._pixmap

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        with stage("canvas.paint"):
            self._paint(event.rect())

    def _paint(self, area: QRect) -> None:
        painter = QPainter(self)
        painter.setClipRect(area)
        painter.fillRect(area, BACKGROUND)
        pixmap = self._scaled_pixmap()
        if pixmap is None:
            return
        target = self.image_rect()
        painter.drawPixmap(target.topLeft(), pixmap)
        if self.tool is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(target.intersected(QRectF(area)))
            self.tool.paint(painter, self)

    # --- мышь --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            x, y = self.to_image(event.position())
            self.tool.press(x, y, HANDLE_TOLERANCE_PX / self.image_scale())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.tool.move(*self.to_image(event.position()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            self.tool.release(*self.to_image(event.position()))
