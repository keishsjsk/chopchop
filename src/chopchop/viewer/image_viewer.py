"""Виджет просмотра фото: вписывание в окно, масштаб колесом, перетаскивание."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QGuiApplication,
    QImage,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QWidget

MIN_ZOOM = 0.05
MAX_ZOOM = 32.0
WHEEL_STEP = 1.25


class ImageViewer(QGraphicsView):
    doubleClicked = Signal()
    zoomChanged = Signal(float)
    navigateRequested = Signal(int)  # колесо в режиме «переключение»: +1 — следующее фото
    contextMenuRequested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setScene(self._scene)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # стрелки обрабатывает окно (листание), а не прокрутка вида
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._fit = True
        self._fit_mode = "fit"  # fit | fit_all | actual
        self._zoom_step = WHEEL_STEP
        self._wheel_navigates = False
        self._pixel_zoom = False
        self._wheel_remainder = 0.0
        self._upscale = False

    def apply_settings(
        self,
        *,
        fit_mode: str,
        zoom_step: float,
        wheel_action: str,
        background: str,
        smoothing: str,
    ) -> None:
        """Параметры просмотра из настроек; действуют сразу, в том числе на открытое фото."""
        self._fit_mode = fit_mode
        self._zoom_step = zoom_step
        self._wheel_navigates = wheel_action == "navigate"
        self._pixel_zoom = smoothing == "pixel"
        self.setBackgroundBrush(QColor(background))
        self._update_smoothing()

    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    def zoom(self) -> float:
        return self.transform().m11()

    def set_image(self, image: QImage) -> None:
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(self._item.boundingRect())
        self.show_initial()

    def show_initial(self) -> None:
        """Масштаб только что открытого фото по настройке: вписать, вписать всегда или 100%."""
        if self._fit_mode == "actual":
            self.actual_size()
            self.centerOn(self._item)
        else:
            self.fit_to_window(upscale=self._fit_mode == "fit_all")

    def replace_image(self, image: QImage) -> None:
        """Подмена уменьшенной копии полной: то, что видит пользователь, не сдвигается."""
        old = self._item.boundingRect()
        if self._fit or old.isEmpty():
            self.set_image(image)
            return
        center = self.mapToScene(self.viewport().rect().center())
        ratio = image.width() / old.width()
        zoom = self.zoom() / ratio
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(self._item.boundingRect())
        self._set_zoom(zoom)
        self.centerOn(center.x() * ratio, center.y() * ratio)

    def fit_to_window(self, upscale: bool | None = None) -> None:
        """Вписать в окно; без upscale маленькие картинки не растягиваются сверх 100%."""
        self._fit = True
        if upscale is None:
            upscale = self._fit_mode == "fit_all"
        self._upscale = upscale
        rect = self._item.boundingRect()
        view = self.viewport().size()
        if rect.isEmpty() or view.isEmpty():
            return
        scale = min(view.width() / rect.width(), view.height() / rect.height())
        if not upscale:
            scale = min(scale, 1.0)
        self._set_zoom(scale)
        self.centerOn(self._item)

    def actual_size(self) -> None:
        self._fit = False
        self._set_zoom(1.0)

    def zoom_by(self, factor: float) -> None:
        self._fit = False
        self._set_zoom(min(max(self.zoom() * factor, MIN_ZOOM), MAX_ZOOM))

    def _set_zoom(self, scale: float) -> None:
        self.setTransform(QTransform.fromScale(scale, scale))
        self._update_smoothing()
        self.zoomChanged.emit(scale)

    def _update_smoothing(self) -> None:
        """При увеличении «пиксельный» режим показывает чёткие квадратики вместо размытия."""
        pixel = self._pixel_zoom and self.zoom() >= 1.0
        self._item.setTransformationMode(
            Qt.TransformationMode.FastTransformation
            if pixel
            else Qt.TransformationMode.SmoothTransformation
        )

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        # Ctrl меняет назначение колеса: масштаб <-> листание
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if steps and self._wheel_navigates != ctrl:
            self._wheel_remainder += steps
            whole = int(self._wheel_remainder)  # плавные тачпады дают дробные шаги
            if whole:
                self._wheel_remainder -= whole
                self.navigateRequested.emit(-whole)  # колесо вперёд — предыдущее фото
        elif steps:
            self.zoom_by(self._zoom_step**steps)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self.fit_to_window(self._upscale)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        # во время перетаскивания (рука) меню не открываем
        if not (QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self.contextMenuRequested.emit(event.globalPos())
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.doubleClicked.emit()
        event.accept()
