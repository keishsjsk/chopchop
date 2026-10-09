"""Рисование: стрелка, рамка, выделение области и свободное рисование мышью (кисть, маркер).

Пока кнопка зажата, результат рисуется поверх холста через QPainter, а движок (Pillow) не
запускается: штрих от руки копится на прозрачном слое размером с холст, и на каждое движение
мыши дорисовывается только новый отрезок. Картинку считает движок один раз, после отпускания.
"""

import math
from typing import Literal

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from chopchop.core.geometry import Rect, simplify_path
from chopchop.core.operations import Annotate, Color, Operation, Stroke
from chopchop.engines.image_engine import ARROW_HEAD_ANGLE, MARKER_ALPHA
from chopchop.ui.tools.base import Tool, ViewMapper

DrawShape = Literal["arrow", "rect", "marker", "pen", "highlighter"]
FREEHAND: frozenset[str] = frozenset({"pen", "highlighter"})
WIDTH_UNIT = 1 / 500  # доля длинной стороны кадра на один пункт толщины
HIGHLIGHTER_WIDTH = 3.0  # маркер шире кисти при той же толщине
HIGHLIGHTER_OPACITY = 0.4
MIN_STEP = 1 / 1500  # точки линии ближе этой доли стороны кадра не записываются
SIMPLIFY = 0.04  # допуск упрощения штриха при отпускании: доля толщины линии


class DrawTool(Tool):
    strokeFinished = Signal()  # линию от руки отпустили: её можно применять сразу
    live = False  # рисуется на холсте самим инструментом, без расчёта картинки движком

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.shape: DrawShape = "pen"
        self.color: Color = (255, 0, 0)
        self.thickness = 4  # пункты 1–20
        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._points: list[tuple[float, float]] = []
        self._dragging = False
        self._frozen = False  # операция передана в историю, след ждёт готового превью
        self._dirty: Rect | None = None
        self._layer: QImage | None = None
        self._layer_key: tuple[object, ...] | None = None
        self._painted = 0  # сколько точек штриха уже нарисовано на слое

    @property
    def freehand(self) -> bool:
        return self.shape in FREEHAND

    def press(self, x: float, y: float, tolerance: float) -> None:
        if self._frozen:
            self._clear()
        self._dragging = True
        if self.freehand:
            self._points = [(x, y)]
            self._painted = 0
        else:
            self._start = self._end = (x, y)
        self._dirty = None
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        if not self._dragging:
            return
        if self.freehand:
            self._add_point(x, y)
        else:
            self._end = (x, y)
            self._dirty = None
        self.changed.emit()

    def release(self, x: float, y: float) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self.freehand:
            self._add_point(x, y)
            # меньше точек — быстрее и расчёт, и файл; видимая форма не меняется
            self._points = list(simplify_path(self._points, max(0.3, self._width() * SIMPLIFY)))
            self._layer_key = None  # слой перерисуется по упрощённой линии
            self._dirty = None
            self.changed.emit()
            self.strokeFinished.emit()
        else:
            self._end = (x, y)
            self._dirty = None
            self.changed.emit()

    def _add_point(self, x: float, y: float) -> None:
        last = self._points[-1] if self._points else None
        if last is None or math.dist(last, (x, y)) >= max(self.long_side * MIN_STEP, 0.5):
            self._points.append((x, y))
            reach = self._width() * (HIGHLIGHTER_WIDTH if self.shape == "highlighter" else 1) + 4
            ax, ay = last if last is not None else (x, y)
            self._dirty = Rect.from_points(ax, ay, x, y)
            self._dirty = Rect(
                self._dirty.x - reach,
                self._dirty.y - reach,
                self._dirty.w + 2 * reach,
                self._dirty.h + 2 * reach,
            )

    def set_options(self, shape: DrawShape, color: Color, thickness: int) -> None:
        if shape != self.shape:
            self._clear()
        self.shape, self.color, self.thickness = shape, color, thickness
        self._layer_key = None
        self.changed.emit()

    def _width(self) -> float:
        return max(2.0, self.thickness * self.long_side * WIDTH_UNIT)

    def pending_operation(self) -> Operation | None:
        if self._frozen:
            return None
        if self.freehand:
            if not self._points:
                return None
            if self.shape == "highlighter":
                return Stroke(
                    tuple(self._points),
                    self.color,
                    self._width() * HIGHLIGHTER_WIDTH,
                    HIGHLIGHTER_OPACITY,
                )
            return Stroke(tuple(self._points), self.color, self._width(), 1.0)
        if self._start is None or self._end is None or self._start == self._end:
            return None
        shape: Literal["arrow", "rect", "marker"] = self.shape  # type: ignore[assignment]
        return Annotate(shape, self._start, self._end, self.color, self._width())

    def dirty_rect(self) -> Rect | None:
        return self._dirty

    def _clear(self) -> None:
        self._start = self._end = None
        self._points = []
        self._dragging = False
        self._frozen = False
        self._dirty = None
        self._layer = None
        self._layer_key = None
        self._painted = 0

    def reset(self) -> None:
        self._clear()
        self.changed.emit()

    def commit(self) -> None:
        self._frozen = True
        self._dragging = False

    def end_commit(self) -> None:
        if self._frozen:
            self._clear()
            self.changed.emit()

    # --- рисование на холсте -----------------------------------------------------------------

    def paint(self, painter: QPainter, view: ViewMapper) -> None:
        if self.freehand:
            self._paint_stroke(painter, view)
            return
        if self._start is None or self._end is None or self._start == self._end:
            return
        origin = view.to_widget(0, 0)
        scale = view.to_widget(1, 0).x() - origin.x()
        width = max(1.0, self._width() * scale)
        start = view.to_widget(*self._start)
        end = view.to_widget(*self._end)
        color = QColor(*self.color)
        if self.shape == "marker":
            fill = QColor(color)
            fill.setAlpha(MARKER_ALPHA)
            painter.fillRect(QRectF(start, end).normalized(), fill)
        elif self.shape == "rect":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawRect(QRectF(start, end).normalized())
        else:
            self._paint_arrow(painter, start, end, width, color)

    @staticmethod
    def _paint_arrow(
        painter: QPainter, start: QPointF, end: QPointF, width: float, color: QColor
    ) -> None:
        length = math.hypot(end.x() - start.x(), end.y() - start.y())
        if length < 1:
            return
        head = min(max(width * 4.0, 12.0), length)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        left = QPointF(
            end.x() - head * math.cos(angle - ARROW_HEAD_ANGLE),
            end.y() - head * math.sin(angle - ARROW_HEAD_ANGLE),
        )
        right = QPointF(
            end.x() - head * math.cos(angle + ARROW_HEAD_ANGLE),
            end.y() - head * math.sin(angle + ARROW_HEAD_ANGLE),
        )
        base = QPointF((left.x() + right.x()) / 2, (left.y() + right.y()) / 2)
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(start, base)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([end, left, right]))

    def _paint_stroke(self, painter: QPainter, view: ViewMapper) -> None:
        if not self._points:
            return
        device = painter.device()
        ratio = device.devicePixelRatioF()
        size = (device.width(), device.height())
        origin = view.to_widget(0, 0)
        scale = view.to_widget(1, 0).x() - origin.x()
        opacity = HIGHLIGHTER_OPACITY if self.shape == "highlighter" else 1.0
        multiplier = HIGHLIGHTER_WIDTH if self.shape == "highlighter" else 1.0
        width = max(1.0, self._width() * multiplier * scale)
        key = (size, ratio, origin.x(), origin.y(), scale, width, self.color)
        layer = self._layer
        if layer is None or key != self._layer_key:
            # холст изменился (размер, масштаб) или штрих упрощён: рисуем заново с начала
            layer = QImage(
                round(size[0] * ratio),
                round(size[1] * ratio),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            layer.setDevicePixelRatio(ratio)
            layer.fill(Qt.GlobalColor.transparent)
            self._layer, self._layer_key, self._painted = layer, key, 0
        if self._painted < len(self._points):
            self._draw_new_segments(layer, view, width)
            self._painted = len(self._points)
        clip = painter.clipBoundingRect()
        source = QRectF(
            clip.x() * ratio, clip.y() * ratio, clip.width() * ratio, clip.height() * ratio
        )
        painter.setOpacity(opacity)
        # слой непрозрачный, прозрачность маркера накладывается целиком: пересечения не темнеют
        painter.drawImage(clip.topLeft(), layer, source)
        painter.setOpacity(1.0)

    def _draw_new_segments(self, layer: QImage, view: ViewMapper, width: float) -> None:
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(*self.color)
        pen = QPen(
            color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
        )
        painter.setPen(pen)
        first = max(self._painted - 1, 0)
        points = [view.to_widget(x, y) for x, y in self._points[first:]]
        if len(points) == 1:
            painter.drawPoint(points[0])
        else:
            painter.drawPolyline(QPolygonF(points))
        painter.end()
