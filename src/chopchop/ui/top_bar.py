"""Верхняя плавающая панель плеера: название файла и кнопка редактирования."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import current, fonts, icons, tokens


class TopBar(FloatingPanel):
    editRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_name = ""
        self._name = QLabel()
        self._name.setFont(fonts.pixel_font(2))
        self._name.setMinimumWidth(0)
        self._edit = QToolButton()
        self._edit.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._edit.setToolTip(self.tr("Редактировать  Ctrl+E"))
        self._edit.setFixedSize(tokens.RAIL_BUTTON, tokens.RAIL_BUTTON)
        self._edit.clicked.connect(self.editRequested)
        self.refresh_theme()
        row = self.horizontal(tokens.SPACE_2)
        row.addWidget(self._name, 1)
        row.addWidget(self._edit)
        self.setFixedHeight(
            tokens.RAIL_BUTTON + 2 * (tokens.BORDER_WIDTH + tokens.SPACE_2) + self.reserve
        )

    def refresh_theme(self) -> None:
        self._edit.setIcon(icons.qicon("edit", current.palette(), logical=32))
        self._edit.setIconSize(QSize(32, 32))

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
