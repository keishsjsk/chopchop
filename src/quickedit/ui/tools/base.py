"""Основа инструментов редактора. Координаты инструментов — в пикселях превью."""

from typing import Protocol

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from quickedit.core.geometry import Rect
from quickedit.core.operations import Operation
from quickedit.core.selection import RectSelection

HANDLE_SIZE = 8.0


class ViewMapper(Protocol):
    """Перевод координат картинки в координаты холста; реализует Canvas."""

    def to_widget(self, x: float, y: float) -> QPointF: ...

    def to_widget_rect(self, rect: Rect) -> QRectF: ...

    def image_rect(self) -> QRectF: ...


class Tool(QObject):
    changed = Signal()
    live = True  # показывать результат ещё до подтверждения

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.bounds = (0.0, 0.0)

    @property
    def long_side(self) -> float:
        return max(self.bounds)

    def set_bounds(self, width: float, height: float) -> None:
        self.bounds = (width, height)

    def press(self, x: float, y: float, tolerance: float) -> None:
        pass

    def move(self, x: float, y: float) -> None:
        pass

    def release(self, x: float, y: float) -> None:
        pass

    def pending_operation(self) -> Operation | None:
        return None

    def reset(self) -> None:
        pass

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        pass


class RectSelectTool(Tool):
    """Инструмент, работающий с выделенной областью; Enter применяет, Esc отменяет."""

    dim_outside = False

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.selection = RectSelection()

    def set_bounds(self, width: float, height: float) -> None:
        super().set_bounds(width, height)
        self.selection.set_bounds(width, height)

    def press(self, x: float, y: float, tolerance: float) -> None:
        self.selection.press(x, y, tolerance)
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        self.selection.drag(x, y)
        self.changed.emit()

    def release(self, x: float, y: float) -> None:
        self.selection.release()
        self.changed.emit()

    def reset(self) -> None:
        self.selection.clear()
        self.changed.emit()

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        rect = self.selection.rect
        if rect is None:
            return
        target = view.to_widget_rect(rect)
        if self.dim_outside:
            full = view.image_rect()
            shade = QColor(0, 0, 0, 140)
            painter.fillRect(
                QRectF(full.left(), full.top(), full.width(), target.top() - full.top()), shade
            )
            painter.fillRect(
                QRectF(full.left(), target.bottom(), full.width(), full.bottom() - target.bottom()),
                shade,
            )
            painter.fillRect(
                QRectF(full.left(), target.top(), target.left() - full.left(), target.height()),
                shade,
            )
            painter.fillRect(
                QRectF(
                    target.right(), target.top(), full.right() - target.right(), target.height()
                ),
                shade,
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("white"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(target)
        painter.setPen(QPen(QColor(30, 30, 30), 1))
        painter.setBrush(QColor("white"))
        half = HANDLE_SIZE / 2
        for hx in (target.left(), target.center().x(), target.right()):
            for hy in (target.top(), target.center().y(), target.bottom()):
                if (hx, hy) != (target.center().x(), target.center().y()):
                    painter.drawRect(QRectF(hx - half, hy - half, HANDLE_SIZE, HANDLE_SIZE))
