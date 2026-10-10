"""Верхняя плавающая панель плеера: название файла (одна строка высотой 32 px).

Переименование и редактирование доступны из контекстного меню и по Ctrl+E, отдельной кнопки нет.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QLabel, QWidget

from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import fonts, tokens


class TopBar(FloatingPanel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_name = ""
        self._name = QLabel()
        self._name.setFont(fonts.pixel_font(2))
        self._name.setMinimumWidth(0)
        row = self.horizontal(0)
        row.setContentsMargins(
            tokens.BORDER_WIDTH + tokens.SPACE_2,
            0,
            tokens.BORDER_WIDTH + tokens.SPACE_2 + self.reserve,
            self.reserve,
        )
        row.addWidget(self._name, 1)
        self.setFixedHeight(tokens.PLAYER_TOP_H)

    def refresh_theme(self) -> None:
        """Название рисуется цветом темы сам; значков на панели больше нет."""
        self.update()

    def set_name(self, name: str) -> None:
        self._full_name = name
        self._elide()

    def text(self) -> str:
        return self._full_name

    def _elide(self) -> None:
        metrics = QFontMetrics(self._name.font())
        room = max(self._name.width(), 80)
        self._name.setText(metrics.elidedText(self._full_name, Qt.TextElideMode.ElideMiddle, room))
        self._name.setToolTip(self._full_name)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()
