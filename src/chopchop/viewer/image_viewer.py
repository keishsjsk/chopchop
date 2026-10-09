"""Виджет просмотра фото: вписывание в окно, масштаб колесом, перетаскивание."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent, QTransform, QWheelEvent
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QWidget

MIN_ZOOM = 0.05
MAX_ZOOM = 32.0
WHEEL_STEP = 1.25


class ImageViewer(QGraphicsView):
    doubleClicked = Signal()
    zoomChanged = Signal(float)

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

    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    def zoom(self) -> float:
        return self.transform().m11()

    def set_image(self, image: QImage) -> None:
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit_to_window()

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

    def fit_to_window(self) -> None:
        """Вписать в окно; маленькие картинки не растягиваются сверх 100%."""
        self._fit = True
        rect = self._item.boundingRect()
        view = self.viewport().size()
        if rect.isEmpty() or view.isEmpty():
            return
        scale = min(view.width() / rect.width(), view.height() / rect.height(), 1.0)
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
        self.zoomChanged.emit(scale)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        if steps:
            self.zoom_by(WHEEL_STEP**steps)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self.fit_to_window()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.doubleClicked.emit()
        event.accept()
