"""Страница видео: кадр mpv и панель управления поверх него, прячется при бездействии мыши."""

from types import ModuleType
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QApplication, QWidget

from quickedit.player.mpv_widget import MpvWidget
from quickedit.player.player import Player
from quickedit.ui.player_controls import PlayerControls

HIDE_DELAY_MS = 2500


class VideoPage(QWidget):
    fullscreenRequested = Signal()

    def __init__(self, module: ModuleType, mpv: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = Player(mpv, self)
        self.video = MpvWidget(module, mpv, self)
        self.controls = PlayerControls(self.player, self)
        self.controls.installEventFilter(self)

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.player.toggle_pause)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._hide_idle)

        self.video.clicked.connect(self._on_click)
        self.video.doubleClicked.connect(self._on_double_click)
        self.video.mouseMoved.connect(self.wake)
        self.controls.fullscreenRequested.connect(self.fullscreenRequested)
        self.player.pausedChanged.connect(lambda paused: self.wake() if paused else None)

    def wake(self) -> None:
        """Показать панель и курсор; спрятать снова, если мышь неподвижна."""
        self.controls.show()
        self.video.unsetCursor()
        self._hide_timer.start()

    def _hide_idle(self) -> None:
        if self.controls.underMouse() or self.player.paused:
            self._hide_timer.start()
            return
        self.controls.hide()
        if self.isActiveWindow():
            self.video.setCursor(Qt.CursorShape.BlankCursor)

    def _on_click(self) -> None:
        # одиночный клик ждёт, не станет ли он двойным (полный экран)
        self._click_timer.start(QApplication.doubleClickInterval())

    def _on_double_click(self) -> None:
        self._click_timer.stop()
        self.fullscreenRequested.emit()

    def release(self) -> None:
        self._hide_timer.stop()
        self._click_timer.stop()
        self.video.release()
        self.player.shutdown()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.video.setGeometry(self.rect())
        height = self.controls.sizeHint().height()
        self.controls.setGeometry(0, self.height() - height, self.width(), height)
        self.controls.raise_()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.controls and event.type() == QEvent.Type.Leave:
            self._hide_timer.start()
        return False
