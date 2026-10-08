"""Слой поверх видео: рамки кадрирования и скрытия, подпись текста, мышь для инструментов."""

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QWidget

from chopchop.core.geometry import Rect
from chopchop.ui.tools.base import Tool

HANDLE_TOLERANCE_PX = 9.0


class VideoOverlay(QWidget):
    """Прозрачный виджет над видео. Координаты инструментов — в пикселях кадра проекта."""

    def __init__(self, host: QWidget, frame_size: tuple[int, int]) -> None:
        super().__init__(host)
        self._host = host
        self._frame = frame_size
        self._crop: Rect | None = None
        self._rotation_note = ""
        self.tool: Tool | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.show()
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self._host
            and event.type() == QEvent.Type.Resize
            and isinstance(event, QResizeEvent)
        ):
            self.setGeometry(self._host.rect())
        return False

    # --- состояние ---------------------------------------------------------------------------

    def set_frame_size(self, size: tuple[int, int]) -> None:
        self._frame = size
        self.update()

    def set_crop(self, rect: Rect | None) -> None:
        self._crop = rect
        self.update()

    def set_rotation_note(self, text: str) -> None:
        self._rotation_note = text
        self.update()

    def set_tool(self, tool: Tool | None) -> None:
        self.tool = tool
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, tool is None)
        self.setCursor(
            Qt.CursorShape.CrossCursor if tool is not None else Qt.CursorShape.ArrowCursor
        )
        self.update()

    # --- перевод координат (ViewMapper) ------------------------------------------------------

    def _scale(self) -> float:
        width, height = self._frame
        if width <= 0 or height <= 0 or self.width() <= 0 or self.height() <= 0:
            return 1.0
        return min(self.width() / width, self.height() / height)

    def image_rect(self) -> QRectF:
        """Где на экране находится кадр: по центру, с чёрными полями, как рисует mpv."""
        scale = self._scale()
        width, height = self._frame[0] * scale, self._frame[1] * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def to_widget(self, x: float, y: float) -> QPointF:
        target = self.image_rect()
        scale = self._scale()
        return QPointF(target.left() + x * scale, target.top() + y * scale)

    def to_widget_rect(self, rect: Rect) -> QRectF:
        top_left = self.to_widget(rect.x, rect.y)
        scale = self._scale()
        return QRectF(top_left.x(), top_left.y(), rect.w * scale, rect.h * scale)

    def to_frame(self, pos: QPointF) -> tuple[float, float]:
        target = self.image_rect()
        scale = self._scale()
        return (pos.x() - target.left()) / scale, (pos.y() - target.top()) / scale

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = self.image_rect()
        if self._crop is not None:
            self._paint_crop(painter, frame)
        if self.tool is not None:
            painter.setClipRect(frame)
            self.tool.paint(painter, self)
            painter.setClipping(False)
        if self._rotation_note:
            painter.setPen(QColor(255, 220, 0))
            painter.drawText(
                QRectF(frame.left() + 8, frame.top() + 6, frame.width(), 20),
                Qt.AlignmentFlag.AlignLeft,
                self._rotation_note,
            )

    def _paint_crop(self, painter: QPainter, frame: QRectF) -> None:
        """Затемнить то, что останется за кадром результата."""
        assert self._crop is not None
        keep = self.to_widget_rect(self._crop)
        shade = QColor(0, 0, 0, 150)
        painter.fillRect(
            QRectF(frame.left(), frame.top(), frame.width(), keep.top() - frame.top()), shade
        )
        painter.fillRect(
            QRectF(frame.left(), keep.bottom(), frame.width(), frame.bottom() - keep.bottom()),
            shade,
        )
        painter.fillRect(
            QRectF(frame.left(), keep.top(), keep.left() - frame.left(), keep.height()), shade
        )
        painter.fillRect(
            QRectF(keep.right(), keep.top(), frame.right() - keep.right(), keep.height()), shade
        )
        painter.setPen(QPen(QColor(255, 200, 0), 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(keep)

    # --- мышь --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            x, y = self.to_frame(event.position())
            self.tool.press(x, y, HANDLE_TOLERANCE_PX / self._scale())
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.tool.move(*self.to_frame(event.position()))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton:
            self.tool.release(*self.to_frame(event.position()))
            self.update()
