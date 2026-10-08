"""Рисование: стрелка, рамка, маркер."""

from PySide6.QtCore import QObject

from quickedit.core.operations import Annotate, Color, Operation, Shape
from quickedit.ui.tools.base import Tool

WIDTH_UNIT = 1 / 500  # доля длинной стороны кадра на один пункт толщины


class DrawTool(Tool):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.shape: Shape = "arrow"
        self.color: Color = (255, 0, 0)
        self.thickness = 4  # пункты 1–20
        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._dragging = False

    def press(self, x: float, y: float, tolerance: float) -> None:
        self._start = self._end = (x, y)
        self._dragging = True
        self.changed.emit()

    def move(self, x: float, y: float) -> None:
        if self._dragging:
            self._end = (x, y)
            self.changed.emit()

    def release(self, x: float, y: float) -> None:
        if self._dragging:
            self._end = (x, y)
            self._dragging = False
            self.changed.emit()

    def set_options(self, shape: Shape, color: Color, thickness: int) -> None:
        self.shape, self.color, self.thickness = shape, color, thickness
        self.changed.emit()

    def pending_operation(self) -> Operation | None:
        if self._start is None or self._end is None or self._start == self._end:
            return None
        width = max(2.0, self.thickness * self.long_side * WIDTH_UNIT)
        return Annotate(self.shape, self._start, self._end, self.color, width)

    def reset(self) -> None:
        self._start = self._end = None
        self._dragging = False
        self.changed.emit()
