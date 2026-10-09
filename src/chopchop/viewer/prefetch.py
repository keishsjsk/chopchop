"""Кэш декодированных фото с фоновой предзагрузкой соседних файлов."""

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from chopchop.viewer.image_loader import load_image, load_reduced


class _JobSignals(QObject):
    done = Signal(Path, object)
    reduced = Signal(Path, object)


class _LoadJob(QRunnable):
    def __init__(self, path: Path, signals: _JobSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals

    def run(self) -> None:
        self._signals.done.emit(self._path, load_image(self._path))


class _ReducedJob(QRunnable):
    def __init__(self, path: Path, max_side: int, signals: _JobSignals) -> None:
        super().__init__()
        self._path = path
        self._max_side = max_side
        self._signals = signals

    def run(self) -> None:
        image = load_reduced(self._path, self._max_side)
        if image is not None:
            self._signals.reduced.emit(self._path, image)


class ImageCache(QObject):
    loaded = Signal(Path, QImage)
    reducedLoaded = Signal(Path, QImage)  # быстрый уменьшенный вариант, полный придёт позже
    failed = Signal(Path)

    def __init__(self, capacity: int = 5, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._capacity = capacity
        self._images: OrderedDict[Path, QImage] = OrderedDict()
        self._pending: set[Path] = set()
        self._signals = _JobSignals()
        self._signals.done.connect(self._on_done)
        self._signals.reduced.connect(self._on_reduced)
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

    def _on_reduced(self, path: Path, image: object) -> None:
        if isinstance(image, QImage):
            self.reducedLoaded.emit(path, image)

    def request_reduced(self, path: Path, max_side: int) -> None:
        """Быстрый уменьшенный вариант в первую очередь: он нужен для первого показа."""
        self._pool.start(_ReducedJob(path, max_side, self._signals), 1)

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
