"""Основа инструментов редактора. Координаты инструментов — в пикселях превью."""

from typing import Protocol

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication

from chopchop.core.geometry import Rect
from chopchop.core.operations import Operation
from chopchop.core.selection import RectSelection
from chopchop.ui.theme import current, tokens
from chopchop.ui.theme.pixel import paint_frame


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

    def cursor_radius(self) -> float | None:
        """Радиус круга-курсора в пикселях кадра (кисть); None — обычный курсор."""
        return None

    def cursor_at(self, x: float, y: float, tolerance: float) -> Qt.CursorShape:
        return Qt.CursorShape.CrossCursor

    def dirty_rect(self) -> Rect | None:
        """Область (в пикселях превью), которую изменило последнее событие; None — всё."""
        return None

    def reset(self) -> None:
        pass

    def commit(self) -> None:
        """Операцию отдали в историю. Пока считается новое превью, след остаётся на экране."""
        self.reset()

    def end_commit(self) -> None:
        """Новое превью готово: след инструмента можно убирать."""

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        pass


class RectSelectTool(Tool):
    """Инструмент, работающий с выделенной областью; Enter применяет, Esc отменяет.

    Рамка в стиле темы: двухпиксельная линия акцентного цвета, ручки 8×8 по углам и серединам
    сторон (область захвата шире), затемнение вне рамки 60%, сетка третей при перетаскивании,
    плашка с размером, привязка к краям и центру кадра в пределах 6 пикселей экрана.
    """

    dim_outside = False

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.selection = RectSelection()
        self.size_scale = 1.0  # во сколько раз итоговый размер больше размера в этих координатах
        self._snap = 0.0

    def set_bounds(self, width: float, height: float) -> None:
        super().set_bounds(width, height)
        self.selection.set_bounds(width, height)

    def press(self, x: float, y: float, tolerance: float) -> None:
        self._snap = tolerance * tokens.SNAP_PX / (tokens.HANDLE_HIT / 2)
        self.selection.press(x, y, tolerance)
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        self.selection.drag(x, y, self._snap)
        self.changed.emit()

    def release(self, x: float, y: float) -> None:
        self.selection.release()
        self.changed.emit()

    def reset(self) -> None:
        self.selection.clear()
        self.changed.emit()

    def cursor_at(self, x: float, y: float, tolerance: float) -> Qt.CursorShape:
        """Курсор по тому, что под указателем: ручки тянут в нужную сторону, внутри — перенос."""
        hit = self.selection.hit(x, y, tolerance)
        if hit is None:
            return Qt.CursorShape.CrossCursor
        if hit == "move":
            return Qt.CursorShape.SizeAllCursor
        if len(hit) == 2:
            diagonal_main = hit in ("tl", "lt", "br", "rb")
            return (
                Qt.CursorShape.SizeFDiagCursor if diagonal_main else Qt.CursorShape.SizeBDiagCursor
            )
        return Qt.CursorShape.SizeHorCursor if hit in ("l", "r") else Qt.CursorShape.SizeVerCursor

    # --- рисование ---------------------------------------------------------------------------

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        rect = self.selection.rect
        if rect is None:
            return
        p = current.palette()
        box = view.to_widget_rect(rect)
        target = QRectF(
            round(box.left()), round(box.top()), round(box.width()), round(box.height())
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self.dim_outside:
            self._paint_dim(painter, view.image_rect(), target)
        accent = QColor(p.accent)
        width = tokens.BORDER_WIDTH
        for edge in (
            QRectF(target.left(), target.top(), target.width(), width),
            QRectF(target.left(), target.bottom() - width, target.width(), width),
            QRectF(target.left(), target.top(), width, target.height()),
            QRectF(target.right() - width, target.top(), width, target.height()),
        ):
            painter.fillRect(edge, accent)
        if self.selection.active:
            self._paint_thirds(painter, target)
        self._paint_handles(painter, target, p.surface_raised, p.accent)
        self._paint_badge(painter, target, view.image_rect(), rect)
        painter.restore()

    @staticmethod
    def _paint_dim(painter: QPainter, full: QRectF, target: QRectF) -> None:
        shade = QColor(*tokens.OVERLAY_DARK, tokens.DIM_ALPHA)
        painter.fillRect(
            QRectF(full.left(), full.top(), full.width(), target.top() - full.top()), shade
        )
        painter.fillRect(
            QRectF(full.left(), target.bottom(), full.width(), full.bottom() - target.bottom()),
            shade,
        )
        painter.fillRect(
            QRectF(full.left(), target.top(), target.left() - full.left(), target.height()), shade
        )
        painter.fillRect(
            QRectF(target.right(), target.top(), full.right() - target.right(), target.height()),
            shade,
        )

    @staticmethod
    def _paint_thirds(painter: QPainter, target: QRectF) -> None:
        line = QColor(*tokens.OVERLAY_LIGHT, 120)
        for index in (1, 2):
            x = round(target.left() + target.width() * index / 3)
            y = round(target.top() + target.height() * index / 3)
            painter.fillRect(QRectF(x, target.top(), 1, target.height()), line)
            painter.fillRect(QRectF(target.left(), y, target.width(), 1), line)

    @staticmethod
    def _paint_handles(painter: QPainter, target: QRectF, fill: str, outline: str) -> None:
        size = tokens.HANDLE_SIZE
        border = tokens.BORDER_WIDTH
        for hx in (target.left(), target.center().x(), target.right()):
            for hy in (target.top(), target.center().y(), target.bottom()):
                if (hx, hy) == (target.center().x(), target.center().y()):
                    continue
                cell = QRectF(round(hx - size / 2), round(hy - size / 2), size, size)
                painter.fillRect(cell, QColor(outline))
                painter.fillRect(cell.adjusted(border, border, -border, -border), QColor(fill))

    def _paint_badge(self, painter: QPainter, target: QRectF, image: QRectF, rect: Rect) -> None:
        """Плашка с итоговым размером «1920×1080» у нижнего края рамки."""
        text = f"{round(rect.w * self.size_scale)}×{round(rect.h * self.size_scale)}"
        font = QFont(QApplication.font())
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 2 * tokens.SPACE_2
        height = metrics.height() + tokens.SPACE_1
        x = target.center().x() - width / 2
        y = target.bottom() - height - tokens.SPACE_2
        if y < target.top() or target.width() < width + tokens.SPACE_2:
            y = max(target.top() - height - tokens.SPACE_1, image.top() + tokens.SPACE_1)
        badge = QRectF(round(x), round(y), width, height)
        p = current.palette()
        paint_frame(painter, badge, fill=p.surface_raised, border=p.accent, shadow=None, step=1)
        painter.setPen(QColor(p.text))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
