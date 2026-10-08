"""Рисование: стрелка, рамка, выделение области и свободное рисование мышью (кисть, маркер)."""

import math
from typing import Literal

from PySide6.QtCore import QObject, Signal

from quickedit.core.operations import Annotate, Color, Operation, Stroke
from quickedit.ui.tools.base import Tool

DrawShape = Literal["arrow", "rect", "marker", "pen", "highlighter"]
FREEHAND: frozenset[str] = frozenset({"pen", "highlighter"})
WIDTH_UNIT = 1 / 500  # доля длинной стороны кадра на один пункт толщины
HIGHLIGHTER_WIDTH = 3.0  # маркер шире кисти при той же толщине
HIGHLIGHTER_OPACITY = 0.4
MIN_STEP = 1 / 1500  # точки линии ближе этой доли стороны кадра не записываются


class DrawTool(Tool):
    strokeFinished = Signal()  # линию от руки отпустили: её можно применять сразу

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.shape: DrawShape = "pen"
        self.color: Color = (255, 0, 0)
        self.thickness = 4  # пункты 1–20
        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._points: list[tuple[float, float]] = []
        self._dragging = False

    @property
    def freehand(self) -> bool:
        return self.shape in FREEHAND

    def press(self, x: float, y: float, tolerance: float) -> None:
        self._dragging = True
        if self.freehand:
            self._points = [(x, y)]
        else:
            self._start = self._end = (x, y)
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        if not self._dragging:
            return
        if self.freehand:
            self._add_point(x, y)
        else:
            self._end = (x, y)
        self.changed.emit()

    def release(self, x: float, y: float) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self.freehand:
            self._add_point(x, y)
            self.changed.emit()
            self.strokeFinished.emit()
        else:
            self._end = (x, y)
            self.changed.emit()

    def _add_point(self, x: float, y: float) -> None:
        last = self._points[-1] if self._points else None
        if last is None or math.dist(last, (x, y)) >= max(self.long_side * MIN_STEP, 0.5):
            self._points.append((x, y))

    def set_options(self, shape: DrawShape, color: Color, thickness: int) -> None:
        if shape != self.shape:
            self._start = self._end = None
            self._points = []
        self.shape, self.color, self.thickness = shape, color, thickness
        self.changed.emit()

    def _width(self) -> float:
        return max(2.0, self.thickness * self.long_side * WIDTH_UNIT)

    def pending_operation(self) -> Operation | None:
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

    def reset(self) -> None:
        self._start = self._end = None
        self._points = []
        self._dragging = False
        self.changed.emit()
