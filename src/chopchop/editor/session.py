"""Сессия редактирования: документ, история операций, превью на прокси и экспорт."""

from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Signal

from chopchop.core.history import History
from chopchop.core.operations import Operation, output_size, scale_operation
from chopchop.engines.image_engine import (
    apply_operation,
    apply_operations,
    make_proxy,
    open_image,
    save_image,
)
from chopchop.workers.tasks import TaskRunner

# EXIF отдаётся вместе с картинкой, чтобы при экспорте его можно было сохранить по желанию
_Loaded = tuple[Image.Image, Image.Exif | None]


class EditSession(QObject):
    loaded = Signal()
    loadFailed = Signal(str)
    changed = Signal()
    exported = Signal(Path)
    exportFailed = Signal(str)

    def __init__(
        self,
        source: Path | None,
        image: Image.Image | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self._memory_image = image  # для картинки из буфера обмена оригинала на диске нет
        self.history = History()
        self._saved_ops: tuple[Operation, ...] = ()
        self._runner = TaskRunner(self)
        self._proxy: Image.Image | None = None
        self._scale = 1.0
        self.original_size = (0, 0)
        self._cached_ops: tuple[Operation, ...] = ()
        self._cached: Image.Image | None = None

    # --- загрузка ----------------------------------------------------------------------------

    def start(self) -> None:
        self._runner.run(self._load_for_preview, self._on_loaded, self.loadFailed.emit)

    def _load_full(self) -> _Loaded:
        if self._memory_image is not None:
            return self._memory_image, None
        if self.source is None:
            raise ValueError("no source")
        return open_image(self.source)

    def _load_for_preview(self) -> tuple[Image.Image, float, tuple[int, int]]:
        image, _ = self._load_full()
        proxy, scale = make_proxy(image)
        return proxy, scale, image.size

    def _on_loaded(self, result: tuple[Image.Image, float, tuple[int, int]]) -> None:
        self._proxy, self._scale, self.original_size = result
        self._cached_ops, self._cached = (), self._proxy
        self.loaded.emit()

    @property
    def is_ready(self) -> bool:
        return self._proxy is not None

    def wait(self) -> None:
        self._runner.wait()

    # --- превью ------------------------------------------------------------------------------

    def preview(self) -> Image.Image:
        """Результат всех операций на уменьшенной копии; пересчитывается только новая часть."""
        if self._proxy is None:
            raise RuntimeError("session is not loaded")
        ops = self.history.operations
        cached_len = len(self._cached_ops)
        if self._cached is not None and ops[:cached_len] == self._cached_ops:
            if cached_len == len(ops):
                return self._cached
            image = apply_operations(self._cached, ops[cached_len:], self._scale)
        else:
            image = apply_operations(self._proxy, ops, self._scale)
        self._cached_ops, self._cached = ops, image
        return image

    def render_with(self, pending: Operation) -> Image.Image:
        """Превью с ещё не применённой операцией (в координатах превью)."""
        return apply_operation(self.preview(), pending)

    def output_size(self) -> tuple[int, int]:
        return output_size(self.history.operations, self.original_size)

    def preview_scale(self) -> float:
        """Во сколько раз полный размер больше превью в текущем состоянии."""
        return self.output_size()[0] / self.preview().width

    # --- правки ------------------------------------------------------------------------------

    def add(self, op_in_preview_coords: Operation) -> None:
        """Добавляет операцию, заданную в пикселях превью; в историю пишется в полном размере."""
        self.history.push(scale_operation(op_in_preview_coords, self.preview_scale()))
        self.changed.emit()

    def add_full(self, op: Operation) -> None:
        """Добавляет операцию, уже заданную в пикселях полного размера."""
        self.history.push(op)
        self.changed.emit()

    def undo(self) -> None:
        if self.history.undo() is not None:
            self.changed.emit()

    def redo(self) -> None:
        if self.history.redo() is not None:
            self.changed.emit()

    @property
    def modified(self) -> bool:
        return self.history.operations != self._saved_ops

    def mark_saved(self, ops: tuple[Operation, ...] | None = None) -> None:
        self._saved_ops = self.history.operations if ops is None else ops

    # --- вывод -------------------------------------------------------------------------------

    def export(self, dest: Path, fmt: str, quality: int = 92, keep_metadata: bool = False) -> None:
        """Применяет операции к оригиналу в фоне и сохраняет в новый файл."""
        ops = self.history.operations

        def job() -> Path:
            image, exif = self._load_full()
            result = apply_operations(image, ops)
            return save_image(result, dest, fmt, quality, exif, keep_metadata)

        def done(path: Path) -> None:
            self.mark_saved(ops)  # правки, сделанные во время экспорта, остаются несохранёнными
            self.exported.emit(path)

        self._runner.run(job, done, self.exportFailed.emit)

    def render_full(self, on_done: Callable[[Image.Image], None]) -> None:
        """Полноразмерный результат в фоне (для копирования в буфер обмена)."""
        ops = self.history.operations

        def job() -> Image.Image:
            image, _ = self._load_full()
            return apply_operations(image, ops)

        self._runner.run(job, on_done, self.exportFailed.emit)
