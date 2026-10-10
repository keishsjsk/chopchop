"""Время показа текста или области скрытия: «с … до …» во времени итога, по умолчанию весь ролик."""

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

from chopchop.ui.theme import tokens

STEP = 0.1


class TimeWindow(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start = self._spin(self.tr("Начало"), self.tr("С какой секунды итога показывать"))
        self._stop = self._spin(self.tr("Конец"), self.tr("До какой секунды итога показывать"))
        caption = QLabel(self.tr("Показ"))
        caption.setProperty("muted", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        row.addWidget(caption)
        row.addWidget(self._start)
        row.addWidget(QLabel("—"))
        row.addWidget(self._stop)
        self.setToolTip(self.tr("Время показа в итоговом ролике; по умолчанию весь ролик"))

    def _spin(self, special: str, tip: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setSingleStep(STEP)
        spin.setSuffix(" " + self.tr("с"))
        spin.setSpecialValueText(special)  # 0 означает «с начала» и «до конца»
        spin.setToolTip(tip)
        spin.setMaximum(0.0)
        spin.valueChanged.connect(lambda _v: self.changed.emit())
        return spin

    def set_duration(self, seconds: float) -> None:
        """Длина итога: выше неё время показа не поставить."""
        for spin in (self._start, self._stop):
            with QSignalBlocker(spin):
                spin.setMaximum(max(round(seconds, 1), 0.0))

    def values(self) -> tuple[float, float]:
        """(с, до) во времени итога; до = -1 — до конца ролика."""
        start = self._start.value()
        stop = self._stop.value()
        if stop <= 0.0:
            return start, -1.0
        return start, max(stop, start + STEP)

    def set_window(self, start: float, stop: float) -> None:
        with QSignalBlocker(self._start), QSignalBlocker(self._stop):
            self._start.setValue(max(start, 0.0))
            self._stop.setValue(0.0 if stop < 0.0 else stop)

    def reset(self) -> None:
        self.set_window(0.0, -1.0)
