"""Сессия редактирования: документ, история операций, превью на прокси и экспорт."""

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Signal

from chopchop.core.history import History
from chopchop.core.operations import Operation, output_size, scale_operation
from chopchop.engines.image_engine import (
    PROXY_SIDE,
    apply_operation,
    apply_operations,
    load_preview,
    make_proxy,
    open_image,
    save_image,
)
from chopchop.services.profiling import stage
from chopchop.workers.tasks import TaskRunner

CACHE_BUDGET = 192 * 1024 * 1024  # байт на кэш промежуточных состояний (отмена и повтор)

# EXIF отдаётся вместе с картинкой, чтобы при экспорте его можно было сохранить по желанию
_Loaded = tuple[Image.Image, Image.Exif | None]


def _size_in_bytes(image: Image.Image) -> int:
    return image.width * image.height * len(image.getbands())


class StateCache:
    """Результаты применения первых n операций, с вытеснением давних по лимиту памяти.

    Ключ — кортеж операций (они неизменяемы и сравниваются по значению), поэтому новая
    операция применяется только к ближайшему закэшированному префиксу, а отмена и повтор
    находят готовую картинку без пересчёта. Доступ из разных потоков под замком.
    """

    def __init__(self, budget: int = CACHE_BUDGET) -> None:
        self._budget = budget
        self._items: OrderedDict[tuple[Operation, ...], Image.Image] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    def get(self, ops: tuple[Operation, ...]) -> Image.Image | None:
        with self._lock:
            image = self._items.get(ops)
            if image is not None:
                self._items.move_to_end(ops)
            return image

    def longest_prefix(self, ops: tuple[Operation, ...]) -> tuple[int, Image.Image] | None:
        """Самый длинный закэшированный префикс (не пустой) и его длина."""
        with self._lock:
            for count in range(len(ops), 0, -1):
                image = self._items.get(ops[:count])
                if image is not None:
                    self._items.move_to_end(ops[:count])
                    return count, image
        return None

    def put(self, ops: tuple[Operation, ...], image: Image.Image) -> None:
        with self._lock:
            if ops in self._items:
                return
            self._items[ops] = image
            self._bytes += _size_in_bytes(image)
            while self._bytes > self._budget and len(self._items) > 1:
                _, dropped = self._items.popitem(last=False)
                self._bytes -= _size_in_bytes(dropped)


class EditSession(QObject):
    loaded = Signal()
    loadFailed = Signal(str)
    changed = Signal()
    previewReady = Signal()  # картинка для текущего списка операций готова (`preview()` мгновенен)
    pendingReady = Signal(object, object, object)  # операция с экрана, результат, готовый кадр
    previewFailed = Signal(str)
    exported = Signal(Path)
    exportFailed = Signal(str)

    def __init__(
        self,
        source: Path | None,
        image: Image.Image | None = None,
        parent: QObject | None = None,
        proxy_side: int = PROXY_SIDE,
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
        self._proxy_side = proxy_side
        self._states = StateCache()
        self._generation = 0  # устаревшие расчёты превью отбрасываются по номеру
        self._pending_generation = 0
        self._busy = 0
        # как превратить результат в картинку для экрана; выполняется в фоновом потоке
        self.frame_converter: Callable[[Image.Image], object] | None = None

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
        if self._memory_image is not None:
            proxy, scale = make_proxy(self._memory_image, self._proxy_side)
            return proxy, scale, self._memory_image.size
        if self.source is None:
            raise ValueError("no source")
        return load_preview(self.source, self._proxy_side)

    def _on_loaded(self, result: tuple[Image.Image, float, tuple[int, int]]) -> None:
        self._proxy, self._scale, self.original_size = result
        self.loaded.emit()

    @property
    def is_ready(self) -> bool:
        return self._proxy is not None

    def wait(self) -> None:
        self._runner.wait()

    # --- превью ------------------------------------------------------------------------------

    def _state(self, ops: tuple[Operation, ...]) -> Image.Image:
        """Результат операций на превью; применяет только то, чего нет в кэше. Любой поток."""
        if self._proxy is None:
            raise RuntimeError("session is not loaded")
        found = self._states.longest_prefix(ops)
        count, image = found if found is not None else (0, self._proxy)
        for index in range(count, len(ops)):
            image = apply_operation(image, scale_operation(ops[index], self._scale))
            self._states.put(ops[: index + 1], image)
        return image

    def preview(self) -> Image.Image:
        """Результат всех операций на уменьшенной копии (в потоке интерфейса — из кэша)."""
        return self._state(self.history.operations)

    def request_preview(self) -> None:
        """Считает превью текущего списка операций в фоне; по готовности — previewReady."""
        ops = self.history.operations
        if not ops or self._states.get(ops) is not None:
            self.previewReady.emit()
            return
        self._generation += 1
        generation = self._generation
        self._busy += 1

        def done(_image: Image.Image) -> None:
            self._busy -= 1
            if generation == self._generation:  # пока считали, список мог измениться
                self.previewReady.emit()

        def failed(error: str) -> None:
            self._busy -= 1
            self.previewFailed.emit(error)

        self._runner.run(lambda: self._state(ops), done, failed)

    def request_pending(self, pending: Operation) -> None:
        """Применяет ещё не сохранённую операцию к превью в фоне; старые ответы отбрасываются."""
        ops = self.history.operations
        self._pending_generation += 1
        generation = self._pending_generation
        self._busy += 1

        def job() -> tuple[Image.Image, object]:
            image = apply_operation(self._state(ops), pending)
            convert = self.frame_converter
            return image, convert(image) if convert is not None else None

        def done(result: tuple[Image.Image, object]) -> None:
            self._busy -= 1
            if generation == self._pending_generation:
                self.pendingReady.emit(pending, *result)

        def failed(error: str) -> None:
            self._busy -= 1
            self.previewFailed.emit(error)

        self._runner.run(job, done, failed)

    def cancel_pending(self) -> None:
        """Ответ на уже запущенный расчёт операции с экрана больше не нужен."""
        self._pending_generation += 1

    @property
    def is_busy(self) -> bool:
        return self._busy > 0

    def render_with(self, pending: Operation) -> Image.Image:
        """Превью с ещё не применённой операцией (в координатах превью), синхронно."""
        return apply_operation(self.preview(), pending)

    def output_size(self) -> tuple[int, int]:
        return output_size(self.history.operations, self.original_size)

    def preview_scale(self) -> float:
        """Во сколько раз полный размер больше превью в текущем состоянии."""
        return self.output_size()[0] / self.preview().width

    # --- правки ------------------------------------------------------------------------------

    def add(self, op_in_preview_coords: Operation, rendered: Image.Image | None = None) -> None:
        """Добавляет операцию, заданную в пикселях превью; в историю пишется в полном размере.

        rendered — уже посчитанный результат этой операции (из живого предпросмотра): так
        применение не повторяет расчёт.
        """
        self.history.push(scale_operation(op_in_preview_coords, self.preview_scale()))
        if rendered is not None:
            self._states.put(self.history.operations, rendered)
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
            with stage("photo.export"):
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
