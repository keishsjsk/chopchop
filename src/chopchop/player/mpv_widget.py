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
    renderContextRecreated = Signal()  # не при первом создании, а при пересоздании

    def __init__(self, module: ModuleType, mpv: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._module = module
        self._mpv = mpv
        self._ctx: Any = None
        self._had_context = False
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
        # при переносе виджета Qt создаёт новый GL-контекст; контекст рендера mpv бывает только один
        self._free_render_context()
        recreated = self._had_context
        self._had_context = True
        self._ctx = self._module.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": self._proc_address},
        )
        # колбэк зовётся из потока mpv, сигнал сам переносит перерисовку в поток интерфейса
        self._ctx.update_cb = self._updateRequested.emit
        # в момент уничтожения контекста он ещё текущий, и ресурсы mpv можно освободить
        self.context().aboutToBeDestroyed.connect(
            self._free_render_context, Qt.ConnectionType.DirectConnection
        )
        if recreated:
            self.renderContextRecreated.emit()

    def _free_render_context(self) -> None:
        if self._ctx is None:
            return
        self._ctx.update_cb = None
        self._ctx.free()
        self._ctx = None

    def paintGL(self) -> None:  # noqa: N802
        if self._ctx is None:
            return
        ratio = self.devicePixelRatioF()
        self._ctx.update()
        self._ctx.render(
            flip_y=True,
            # по умолчанию render() ждёт момента показа кадра и держит поток интерфейса до
            # целого кадра видео (20-30 мс); мы показываем кадр сразу, как он готов
            block_for_target_time=False,
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
        self._free_render_context()
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
