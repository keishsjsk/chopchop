"""Выбор пропорций кадра (1:1, 4:3, 16:9 …) для кадрирования фото и видео."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QToolButton, QWidget

from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.ui.tools.crop_tool import Ratio

RATIOS: tuple[tuple[str, Ratio], ...] = (
    (QT_TRANSLATE_NOOP("CropRatioBar", "Свободно"), None),
    (QT_TRANSLATE_NOOP("CropRatioBar", "Исходное"), "original"),
    ("1:1", 1.0),
    ("4:3", 4 / 3),
    ("3:2", 3 / 2),
    ("16:9", 16 / 9),
    ("21:9", 21 / 9),
    ("3:4", 3 / 4),
    ("2:3", 2 / 3),
    ("9:16", 9 / 16),
)
SAME = 1e-6


def inverse(ratio: Ratio) -> Ratio:
    """Те же пропорции, повёрнутые на 90°: 16:9 → 9:16; None остаётся свободным."""
    if ratio == "original":
        return "original_flipped"
    if ratio == "original_flipped":
        return "original"
    if isinstance(ratio, float):
        return 1 / ratio
    return None


class CropRatioBar(QWidget):
    ratioChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._combo = QComboBox()
        for title, ratio in RATIOS:
            self._combo.addItem(self.tr(title), ratio)
        self._custom_index = -1  # служебный пункт для перевёрнутых «исходных» пропорций
        self._combo.currentIndexChanged.connect(self._emit)
        self._swap = QToolButton()
        self._swap.setText("⇄")
        self._swap.setToolTip(self.tr("Повернуть пропорции: 16:9 ↔ 9:16"))
        self._swap.clicked.connect(self.swap)
        self._swap.setEnabled(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._combo)
        row.addWidget(self._swap)

    def value(self) -> Ratio:
        data = self._combo.currentData()
        return data if data is None or isinstance(data, float | str) else float(data)

    def _emit(self) -> None:
        self._swap.setEnabled(self.value() is not None)
        self.ratioChanged.emit(self.value())

    def swap(self) -> None:
        self.set_value(inverse(self.value()))

    def set_value(self, ratio: Ratio) -> None:
        index = self._find(ratio)
        if index < 0:
            index = self._custom_item(ratio)
        self._combo.setCurrentIndex(index)

    def _find(self, ratio: Ratio) -> int:
        for index in range(self._combo.count()):
            data = self._combo.itemData(index)
            if isinstance(ratio, float) and isinstance(data, float):
                if abs(ratio - data) < SAME and index != self._custom_index:
                    return index
            elif data == ratio and index != self._custom_index:
                return index
        return -1

    def _custom_item(self, ratio: Ratio) -> int:
        title = self.tr("Исходное, повёрнутое") if ratio == "original_flipped" else f"{ratio:.2f}"
        if self._custom_index < 0:
            self._combo.addItem(title, ratio)
            self._custom_index = self._combo.count() - 1
        else:
            self._combo.setItemText(self._custom_index, title)
            self._combo.setItemData(self._custom_index, ratio)
        return self._custom_index
