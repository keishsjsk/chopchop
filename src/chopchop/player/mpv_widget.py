"""Виджет, в который mpv рисует кадры через render API (Windows, X11 и Wayland)."""

import ctypes
from types import ModuleType
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QOpenGLContext, QPainter, QPaintEvent
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


class _SwSize(ctypes.Structure):
    _fields_ = (("w", ctypes.c_int), ("h", ctypes.c_int))


class _SwStride(ctypes.Structure):
    _fields_ = (("value", ctypes.c_size_t),)


def _register_software_params(module: ModuleType) -> None:
    """Учит python-mpv параметрам программного рендера (`MPV_RENDER_PARAM_SW_*` из render.h)."""
    types = module.MpvRenderParam.TYPES
    types.setdefault("sw_size", (17, _SwSize))
    types.setdefault("sw_format", (18, str))
    types.setdefault("sw_stride", (19, _SwStride))
    types.setdefault("sw_pointer", (20, ctypes.c_void_p))


class SoftwareMpvWidget(QWidget):
    """Тот же плеер без OpenGL: mpv рисует кадр в память (render API `sw`), окно обычное растровое.

    Нужен там, где нет аппаратного OpenGL или он тормозит (виртуальные машины, старые драйверы,
    гибридные ноутбуки): окно не проходит через GL и не копируется между видеокартами.
    Интерфейс тот же, что у `MpvWidget`.

    В программном режиме mpv не зовёт обратный вызов на каждый кадр, пока его не опрашивают, поэтому
    таймер каждые 8 мс спрашивает «есть ли новый кадр» (это дешёвый вызов); без нового кадра прежняя
    картинка остаётся на месте, и при перезагрузке монтажа она не мигает чёрным.
    """

    clicked = Signal()
    doubleClicked = Signal()
    mouseMoved = Signal()
    _updateRequested = Signal()
    renderContextRecreated = Signal()  # здесь контекст не пересоздаётся; сигнал для совместимости
    POLL_MS = 8

    def __init__(self, module: ModuleType, mpv: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _register_software_params(module)
        self._module = module
        self._mpv = mpv
        self._ctx: Any = module.MpvRenderContext(mpv, "sw")
        self._frame = QImage()
        self._has_frame = False
        self._fresh = False
        self._updateRequested.connect(self._poll)
        self._ctx.update_cb = lambda: self._updateRequested.emit()  # зовётся из потока mpv
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def _poll(self) -> None:
        """Новый кадр от mpv готов: просим перерисовку (сам кадр рисуется в `paintEvent`)."""
        if self._ctx is not None and self._ctx.update():
            self._fresh = True
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._ctx is None:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
            return
        ratio = self.devicePixelRatioF()
        width, height = max(int(self.width() * ratio), 1), max(int(self.height() * ratio), 1)
        resized = self._frame.width() != width or self._frame.height() != height
        if resized:
            self._frame = QImage(width, height, QImage.Format.Format_RGB32)
            self._frame.fill(Qt.GlobalColor.black)
            self._frame.setDevicePixelRatio(ratio)
        if self._fresh or (resized and self._has_frame):
            self._fresh = False
            self._has_frame = True
            bits = self._frame.bits()
            address = ctypes.addressof(ctypes.c_char.from_buffer(bits))
            self._ctx.render(
                sw_size={"w": width, "h": height},
                sw_format="bgr0",  # байты B, G, R, пусто: это `Format_RGB32` в памяти
                sw_stride={"value": self._frame.bytesPerLine()},
                sw_pointer=address,
                block_for_target_time=False,
            )
        painter.drawImage(0, 0, self._frame)

    def release(self) -> None:
        """Освободить контекст рендера; вызывать до остановки mpv."""
        if self._ctx is None:
            return
        self._timer.stop()
        self._ctx.update_cb = None
        self._ctx.free()
        self._ctx = None

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


def create_video_widget(
    module: ModuleType, mpv: Any, parent: QWidget | None = None
) -> "MpvWidget | SoftwareMpvWidget":
    """Видеовиджет по выбранному режиму рендера: OpenGL или программный."""
    from chopchop.services import graphics

    if graphics.software():
        return SoftwareMpvWidget(module, mpv, parent)
    return MpvWidget(module, mpv, parent)
