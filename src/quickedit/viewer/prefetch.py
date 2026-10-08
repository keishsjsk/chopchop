"""Кэш декодированных фото с фоновой предзагрузкой соседних файлов."""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from quickedit.viewer.image_loader import load_image


class _JobSignals(QObject):
    done = Signal(Path, object)


class _LoadJob(QRunnable):
    def __init__(self, path: Path, signals: _JobSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals

    def run(self) -> None:
        self._signals.done.emit(self._path, load_image(self._path))


class ImageCache(QObject):
    loaded = Signal(Path, QImage)
    failed = Signal(Path)

    def __init__(self, capacity: int = 5, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._capacity = capacity
        self._images: OrderedDict[Path, QImage] = OrderedDict()
        self._pending: set[Path] = set()
        self._signals = _JobSignals()
        self._signals.done.connect(self._on_done)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

    def get(self, path: Path) -> QImage | None:
        image = self._images.get(path)
        if image is not None:
            self._images.move_to_end(path)
        return image

    def request(self, path: Path) -> None:
        if path in self._images or path in self._pending:
            return
        self._pending.add(path)
        self._pool.start(_LoadJob(path, self._signals))

    def wait(self) -> None:
        """Дождаться фоновых задач (нужно при закрытии окна и в тестах)."""
        self._pool.waitForDone()

    def _on_done(self, path: Path, image: object) -> None:
        self._pending.discard(path)
        if not isinstance(image, QImage):
            self.failed.emit(path)
            return
        self._images[path] = image
        while len(self._images) > self._capacity:
            self._images.popitem(last=False)
        self.loaded.emit(path, image)
