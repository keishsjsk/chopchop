"""Цветокоррекция: ползунки яркости, контраста, насыщенности и гаммы."""

from chopchop.core.operations import Adjust, Operation
from chopchop.ui.tools.base import Tool


class AdjustTool(Tool):
    def __init__(self) -> None:
        super().__init__()
        self.values = Adjust()

    def set_values(self, values: Adjust) -> None:
        self.values = values
        self.changed.emit()

    def pending_operation(self) -> Operation | None:
        return None if self.values.is_identity else self.values

    def reset(self) -> None:
        self.values = Adjust()
        self.changed.emit()
