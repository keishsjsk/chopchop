"""Ненавязчивые уведомления внизу окна: «Сохранено» с действием, ошибка. Окон с кнопкой «ОК» нет."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QSize, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import current, icons, tokens

AUTO_HIDE_MS = 6000
BOTTOM_GAP = tokens.SPACE_6 + tokens.SPACE_6  # над плавающей панелью плеера и редактора
KIND_ICON = {"success": "check", "error": "warning", "info": "info"}
KIND_ROLE = {"success": "success", "error": "danger", "info": "secondary"}


class Toast(FloatingPanel):
    """Одно уведомление; новое сообщение заменяет предыдущее."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._icon = QLabel()
        self._icon.setFixedSize(QSize(32, 32))
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setMaximumWidth(520)
        self._action = QPushButton()
        self._action.setProperty("variant", "flat")
        self._close = QPushButton("×")
        self._close.setProperty("variant", "flat")
        self._close.setFixedWidth(tokens.MIN_HIT)
        self._close.clicked.connect(self.disappear)
        self._callback: Callable[[], None] | None = None
        self._action.clicked.connect(self._on_action)
        row = self.horizontal(tokens.SPACE_2)
        row.addWidget(self._icon)
        row.addWidget(self._text, 1)
        row.addWidget(self._action)
        row.addWidget(self._close)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTO_HIDE_MS)
        self._timer.timeout.connect(self.disappear)
        parent.installEventFilter(self)
        self.hide()

    def show_message(
        self,
        text: str,
        kind: str = "info",
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        p = current.palette()
        pixmap: QPixmap = icons.pixmap(
            KIND_ICON.get(kind, "info"),
            p,
            logical=32,
            ratio=self.devicePixelRatioF(),
            role=KIND_ROLE.get(kind, "secondary"),
        )
        self._icon.setPixmap(pixmap)
        self._text.setText(text)
        self._callback = action
        self._action.setText(action_text or "")
        self._action.setVisible(bool(action_text and action))
        self.adjustSize()
        self._place()
        self.raise_()
        self.appear()
        self._timer.start()

    def _on_action(self) -> None:
        callback = self._callback
        self.disappear()
        if callback is not None:
            callback()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        size = self.sizeHint()
        self.resize(size)
        self.move(
            (parent.width() - size.width()) // 2, parent.height() - size.height() - BOTTOM_GAP
        )

    def message(self) -> str:
        return self._text.text()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802
        self._timer.stop()  # пока на уведомлении курсор, оно не исчезает

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        if self.isVisible():
            self._timer.start()
