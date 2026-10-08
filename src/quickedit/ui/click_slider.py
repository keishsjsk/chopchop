"""Ползунок, который по клику сразу прыгает в точку клика (и продолжает тащиться мышью)."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class ClickSlider(QSlider):
    def _value_at(self, position: QPointF) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        if self.orientation() == Qt.Orientation.Horizontal:
            span = groove.width() - handle.width()
            offset = position.x() - groove.x() - handle.width() / 2
        else:
            span = groove.height() - handle.height()
            offset = position.y() - groove.y() - handle.height() / 2
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            round(offset),
            max(span, 1),
            option.upsideDown,
        )

    def _jump(self, event: QMouseEvent) -> None:
        value = self._value_at(event.position())
        self.setValue(value)
        self.sliderMoved.emit(value)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._jump(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.isSliderDown():
            self._jump(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
