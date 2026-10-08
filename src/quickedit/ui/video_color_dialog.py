"""Цветокоррекция и фильтр видео: ползунки с живым предпросмотром."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from quickedit.core.operations import Adjust, FilterName

GAMMA_RANGE = 50.0  # положение ползунка гаммы: 2 ** (значение / 50)
FILTERS: tuple[tuple[str, FilterName | None], ...] = (
    ("Без фильтра", None),
    ("Чёрно-белое", "grayscale"),
    ("Сепия", "sepia"),
    ("Резкость", "sharpen"),
    ("Размытие", "blur"),
)


def slider_to_adjust(values: dict[str, int]) -> Adjust:
    return Adjust(
        brightness=1 + values["brightness"] / 100,
        contrast=1 + values["contrast"] / 100,
        saturation=1 + values["saturation"] / 100,
        gamma=2 ** (values["gamma"] / GAMMA_RANGE),
    )


def adjust_to_slider(adjust: Adjust) -> dict[str, int]:
    import math

    return {
        "brightness": round((adjust.brightness - 1) * 100),
        "contrast": round((adjust.contrast - 1) * 100),
        "saturation": round((adjust.saturation - 1) * 100),
        "gamma": round(math.log2(adjust.gamma) * GAMMA_RANGE),
    }


class VideoColorDialog(QDialog):
    """Изменения сразу видны в превью; «Отмена» возвращает прежний вид."""

    previewChanged = Signal(object, object)  # Adjust, имя фильтра или None

    def __init__(
        self, adjust: Adjust, filter_name: FilterName | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Цвет и фильтры"))
        self._sliders: dict[str, QSlider] = {}
        form = QFormLayout()
        start = adjust_to_slider(adjust)
        for key, label in (
            ("brightness", self.tr("Яркость")),
            ("contrast", self.tr("Контраст")),
            ("saturation", self.tr("Насыщенность")),
            ("gamma", self.tr("Гамма")),
        ):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.setValue(start[key])
            slider.valueChanged.connect(self._emit_preview)
            self._sliders[key] = slider
            form.addRow(label, slider)

        self._filter = QComboBox()
        for title, name in FILTERS:
            self._filter.addItem(self.tr(title), name)
        self._filter.setCurrentIndex(max(self._filter.findData(filter_name), 0))
        self._filter.currentIndexChanged.connect(self._emit_preview)
        form.addRow(self.tr("Фильтр"), self._filter)

        reset = QPushButton(self.tr("Сбросить"))
        reset.clicked.connect(self._reset)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(self.tr("Изменения видны в превью, применятся при экспорте.")))
        layout.addWidget(reset)
        layout.addWidget(buttons)
        self.setMinimumWidth(360)

    def adjust(self) -> Adjust:
        return slider_to_adjust({key: slider.value() for key, slider in self._sliders.items()})

    def filter_name(self) -> FilterName | None:
        data = self._filter.currentData()
        return data if data is not None else None

    def _reset(self) -> None:
        for slider in self._sliders.values():
            slider.blockSignals(True)
            slider.setValue(0)
            slider.blockSignals(False)
        self._filter.blockSignals(True)
        self._filter.setCurrentIndex(0)
        self._filter.blockSignals(False)
        self._emit_preview()

    def _emit_preview(self) -> None:
        self.previewChanged.emit(self.adjust(), self.filter_name())
