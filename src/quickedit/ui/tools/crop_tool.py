"""Кадрирование: выделить область, Enter — обрезать."""

from quickedit.core.operations import Crop, Operation
from quickedit.ui.tools.base import RectSelectTool


class CropTool(RectSelectTool):
    live = False
    dim_outside = True

    def pending_operation(self) -> Operation | None:
        rect = self.selection.rect
        return Crop(rect) if rect is not None else None
