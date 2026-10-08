"""Виджет, в который mpv рисует кадры через render API (Windows, X11 и Wayland)."""

from types import ModuleType
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget


class MpvWidget(QOpenGLWidget):
    clicked = Signal()
    doubleClicked = Signal()
    mouseMoved = Signal()
    _updateRequested = Signal()

    def __init__(self, module: ModuleType, mpv: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._module = module
        self._mpv = mpv
        self._ctx: Any = None
        # ссылка на C-обёртку должна жить, пока жив контекст
        self._proc_address = module.MpvGlGetProcAddressFn(self._get_proc_address)
        self._updateRequested.connect(self.update)
        self.setMouseTracking(True)

    @staticmethod
    def _get_proc_address(_ctx: object, name: bytes) -> int:
        gl = QOpenGLContext.currentContext()
        if gl is None:
            return 0
        address = gl.getProcAddress(name)
        return int(address) if address else 0

    def initializeGL(self) -> None:  # noqa: N802
        self._ctx = self._module.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": self._proc_address},
        )
        # колбэк зовётся из потока mpv, сигнал сам переносит перерисовку в поток интерфейса
        self._ctx.update_cb = self._updateRequested.emit

    def paintGL(self) -> None:  # noqa: N802
        if self._ctx is None:
            return
        ratio = self.devicePixelRatioF()
        self._ctx.update()
        self._ctx.render(
            flip_y=True,
            opengl_fbo={
                "w": int(self.width() * ratio),
                "h": int(self.height() * ratio),
                "fbo": self.defaultFramebufferObject(),
            },
        )

    def release(self) -> None:
        """Освободить контекст рендера; вызывать до остановки mpv."""
        if self._ctx is None:
            return
        self.makeCurrent()
        self._ctx.update_cb = None
        self._ctx.free()
        self._ctx = None
        self.doneCurrent()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.doubleClicked.emit()
        event.accept()
