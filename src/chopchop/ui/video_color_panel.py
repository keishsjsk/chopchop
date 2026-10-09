"""Цвет и фильтры видео: ползунки и выбор фильтра в контекстной панели, живой предпросмотр."""

import math

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget

from chopchop.core.operations import Adjust, FilterName
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.theme import tokens
from chopchop.ui.widgets import button

GAMMA_RANGE = 50.0  # положение ползунка гаммы: 2 ** (значение / 50)
COMMIT_MS = 350  # значения попадают в историю одним шагом, когда ползунок замер
SLIDER_WIDTH = 6 * tokens.SPACE_4
FILTERS: tuple[tuple[str, FilterName | None], ...] = (
    (QT_TRANSLATE_NOOP("VideoColorPanel", "Без фильтра"), None),
    (QT_TRANSLATE_NOOP("VideoColorPanel", "Чёрно-белое"), "grayscale"),
    (QT_TRANSLATE_NOOP("VideoColorPanel", "Сепия"), "sepia"),
    (QT_TRANSLATE_NOOP("VideoColorPanel", "Резкость"), "sharpen"),
    (QT_TRANSLATE_NOOP("VideoColorPanel", "Размытие"), "blur"),
)


def slider_to_adjust(values: dict[str, int]) -> Adjust:
    return Adjust(
        brightness=1 + values["brightness"] / 100,
        contrast=1 + values["contrast"] / 100,
        saturation=1 + values["saturation"] / 100,
        gamma=2 ** (values["gamma"] / GAMMA_RANGE),
    )


def adjust_to_slider(adjust: Adjust) -> dict[str, int]:
    return {
        "brightness": round((adjust.brightness - 1) * 100),
        "contrast": round((adjust.contrast - 1) * 100),
        "saturation": round((adjust.saturation - 1) * 100),
        "gamma": round(math.log2(adjust.gamma) * GAMMA_RANGE),
    }


class ColorPanel(QWidget):
    """Ползунки и фильтр в одну строку. Изменения сразу видны в превью.

    `previewChanged` идёт на каждое движение, `committed` — когда значения замерли на
    `COMMIT_MS`: тогда страница записывает их в историю одним шагом.
    """

    previewChanged = Signal(object, object)  # Adjust, имя фильтра или None
    committed = Signal(object, object)

    def __init__(self, adjust: Adjust | None = None, filter_name: FilterName | None = None) -> None:
        super().__init__()
        self._sliders: dict[str, QSlider] = {}
        self._labels: dict[str, str] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        for key, label in (
            ("brightness", self.tr("Яркость")),
            ("contrast", self.tr("Контраст")),
            ("saturation", self.tr("Насыщенность")),
            ("gamma", self.tr("Гамма")),
        ):
            slider = ClickSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.setFixedWidth(SLIDER_WIDTH)
            slider.setAccessibleName(label)
            slider.valueChanged.connect(self._on_changed)
            self._sliders[key] = slider
            self._labels[key] = label
            caption = QLabel(label)
            caption.setProperty("muted", True)
            row.addWidget(caption)
            row.addWidget(slider)
        self._filter = QComboBox()
        for title, name in FILTERS:
            self._filter.addItem(self.tr(title), name)
        self._filter.currentIndexChanged.connect(self._on_changed)
        self._filter.setAccessibleName(self.tr("Фильтр"))
        row.addWidget(self._filter)
        self._reset_button = button(self.tr("Сбросить"), tooltip=self.tr("Вернуть всё как было"))
        self._reset_button.clicked.connect(self._reset)
        row.addWidget(self._reset_button)
        row.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COMMIT_MS)
        self._timer.timeout.connect(self._commit)
        self.set_values(adjust or Adjust(), filter_name)

    # --- значения ----------------------------------------------------------------------------

    def adjust(self) -> Adjust:
        return slider_to_adjust({key: slider.value() for key, slider in self._sliders.items()})

    def filter_name(self) -> FilterName | None:
        data = self._filter.currentData()
        return data if data is not None else None

    def dragging(self) -> bool:
        return any(slider.isSliderDown() for slider in self._sliders.values())

    def set_values(self, adjust: Adjust, filter_name: FilterName | None) -> None:
        """Показать значения проекта; не трогает ползунки, пока их двигают."""
        if self.dragging() or self._timer.isActive():
            return
        values = adjust_to_slider(adjust)
        for key, slider in self._sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(values[key])
        with QSignalBlocker(self._filter):
            self._filter.setCurrentIndex(max(self._filter.findData(filter_name), 0))
        self._tooltips()

    def _tooltips(self) -> None:
        for key, slider in self._sliders.items():
            slider.setToolTip(f"{self._labels[key]}: {slider.value():+d}")

    def _on_changed(self) -> None:
        self._tooltips()
        self.previewChanged.emit(self.adjust(), self.filter_name())
        self._timer.start()

    def _commit(self) -> None:
        self.committed.emit(self.adjust(), self.filter_name())

    def _reset(self) -> None:
        for slider in self._sliders.values():
            with QSignalBlocker(slider):
                slider.setValue(0)
        with QSignalBlocker(self._filter):
            self._filter.setCurrentIndex(0)
        self._on_changed()  # один сигнал, а не по одному на каждый ползунок
