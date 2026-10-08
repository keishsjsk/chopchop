"""Кадрирование: сразу выделен весь кадр, края можно двигать; пропорции — на выбор."""

from PySide6.QtCore import QObject

from quickedit.core.operations import Crop, Operation
from quickedit.ui.tools.base import RectSelectTool

# значение пропорций: None — свободно, число — ширина / высота,
# "original" — как у кадра, "original_flipped" — как у кадра, но перевёрнутые
Ratio = float | str | None
COVERS_TOLERANCE = 0.5  # пикселей: рамка с такими отступами считается «весь кадр»


class CropTool(RectSelectTool):
    live = False
    dim_outside = True

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ratio: Ratio = None

    @property
    def ratio(self) -> Ratio:
        return self._ratio

    def aspect(self) -> float | None:
        """Текущие пропорции числом (ширина / высота) или None, если свободно."""
        width, height = self.bounds
        if self._ratio == "original" and height > 0:
            return width / height
        if self._ratio == "original_flipped" and width > 0:
            return height / width
        return self._ratio if isinstance(self._ratio, float) else None

    def set_ratio(self, ratio: Ratio) -> None:
        self._ratio = float(ratio) if isinstance(ratio, int | float) else ratio
        self.selection.set_aspect(self.aspect())
        self.changed.emit()

    def set_bounds(self, width: float, height: float) -> None:
        super().set_bounds(width, height)
        self.selection.set_aspect(self.aspect())  # «исходные» пропорции зависят от размера кадра

    def select_all(self) -> None:
        """Выделить весь кадр: пользователь сразу видит рамку и может её менять."""
        self.selection.select_all()
        self.changed.emit()

    def covers_frame(self) -> bool:
        rect = self.selection.rect
        if rect is None:
            return False
        width, height = self.bounds
        return (
            rect.x <= COVERS_TOLERANCE
            and rect.y <= COVERS_TOLERANCE
            and rect.right >= width - COVERS_TOLERANCE
            and rect.bottom >= height - COVERS_TOLERANCE
        )

    def pending_operation(self) -> Operation | None:
        rect = self.selection.rect
        if rect is None or self.covers_frame():
            return None  # рамка по всему кадру ничего не меняет
        return Crop(rect)
