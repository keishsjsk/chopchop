"""Встроенная полоса экспорта: прогресс и кнопка «Отмена» прямо в окне, без блокирующих диалогов."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from chopchop.ui.theme import tokens


class ExportStrip(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(tokens.SPACE_3)
        self._cancel = QPushButton(self.tr("Отмена"))
        self._cancel.clicked.connect(self.cancelRequested)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        row.addWidget(self._label)
        row.addWidget(self._bar, 1)
        row.addWidget(self._cancel)
        self.hide()

    @property
    def active(self) -> bool:
        return not self.isHidden()

    def start(self, text: str, indeterminate: bool = False) -> None:
        self._label.setText(text)
        self._bar.setRange(0, 0 if indeterminate else 100)
        self._bar.setValue(0)
        self._cancel.setEnabled(True)
        self.show()

    def set_fraction(self, fraction: float) -> None:
        if self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._bar.setValue(round(min(max(fraction, 0.0), 1.0) * 100))

    def cancelling(self) -> None:
        self._cancel.setEnabled(False)
        self._label.setText(self.tr("Отмена…"))

    def finish(self) -> None:
        self.hide()

    def value(self) -> int:
        return int(self._bar.value())
