"""Миниатюры для полосы обрезки: пачками, в фоне, с отменой и дисковым кэшем."""

import contextlib
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from chopchop.engines.video_engine import THUMB_WIDTH, thumbnail_args, thumbnail_batch_args
from chopchop.services import cache
from chopchop.services.process import no_window_flags
from chopchop.services.profiling import stage

THUMB_TIMEOUT = 20
BATCH_TIMEOUT = 60
PARALLEL = 3  # одновременных запусков ffmpeg: запуск тяжёлый, больше — мешает плееру
POLL = 0.01


def extract_thumbnail(ffmpeg: Path, path: Path, at: float) -> bytes:
    """PNG-кадр на заданной секунде; пустые байты, если кадр достать не удалось."""
    try:
        result = subprocess.run(
            thumbnail_args(ffmpeg, path, at),
            capture_output=True,
            timeout=THUMB_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=no_window_flags(),
        )
    except subprocess.TimeoutExpired:
        return b""
    return result.stdout if result.returncode == 0 else b""


def extract_batch(
    ffmpeg: Path,
    path: Path,
    frames: list[tuple[float, Path]],
    cancel: threading.Event,
) -> bool:
    """Достаёт несколько кадров одним процессом; False, если отменили или не получилось."""
    args = thumbnail_batch_args(ffmpeg, path, frames)
    with stage("video.thumb_batch"):
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window_flags(),
        )
        waited = 0.0
        while True:
            try:
                return process.wait(timeout=POLL) == 0
            except subprocess.TimeoutExpired:
                waited += POLL
                if cancel.is_set() or waited > BATCH_TIMEOUT:
                    process.kill()
                    process.wait()
                    return False


class _Signals(QObject):
    ready = Signal(str, int, QImage)


class _Batch(QRunnable):
    def __init__(
        self,
        loader: "ThumbnailLoader",
        generation: int,
        path: Path,
        items: list[tuple[int, float, Path]],
    ) -> None:
        super().__init__()
        self._loader = loader
        self._generation = generation
        self._path = path
        self._items = items

    def run(self) -> None:
        loader = self._loader
        if loader.generation != self._generation:
            return  # пока ждали очереди, открыли другой клип
        # своё имя временного файла у каждого поколения: прерванная пачка не трогает файлы новой
        suffix = f".{self._generation}.part.jpg"
        frames = [(at, dest.with_suffix(suffix)) for _, at, dest in self._items]
        finished = extract_batch(loader.ffmpeg, self._path, frames, loader.cancel_flag)
        if not finished:
            # отменили или ffmpeg упал: недописанные кадры не публикуем
            for _, part in frames:
                part.unlink(missing_ok=True)
            return
        for (index, _, dest), (_, part) in zip(self._items, frames, strict=True):
            if part.exists():
                with contextlib.suppress(OSError):
                    part.replace(dest)
            image = QImage(str(dest)) if dest.exists() else QImage()
            if not image.isNull() and loader.generation == self._generation:
                loader.signals.ready.emit(str(self._path), index, image)
        for _, part in frames:
            part.unlink(missing_ok=True)


class _Lookup(QRunnable):
    """Всё дорогое при открытии клипа: чистка кэша, чтение готовых миниатюр с диска, пачки ffmpeg.

    Выполняется в фоне, чтобы открытие редактора не ждало диска; интерфейс получает заглушки
    и подменяет их по мере готовности.
    """

    def __init__(
        self, loader: "ThumbnailLoader", generation: int, path: Path, duration: float, count: int
    ) -> None:
        super().__init__()
        self._loader = loader
        self._generation = generation
        self._path = path
        self._duration = duration
        self._count = count

    def run(self) -> None:
        loader = self._loader
        folder = loader.prepare_folder()
        missing: list[tuple[int, float, Path]] = []
        identity = cache.file_identity(self._path)
        for index in range(self._count):
            if loader.generation != self._generation:
                return
            dest = folder / f"{cache.key_for(identity, index, self._count, loader.width)}.jpg"
            at = self._duration * (index + 0.5) / self._count
            if dest.stem in loader.memory_keys():
                continue  # уже в памяти: интерфейс показал её сразу
            image = QImage(str(dest)) if dest.exists() else QImage()
            if image.isNull():
                missing.append((index, at, dest))
            else:
                loader.signals.ready.emit(str(self._path), index, image)
        for batch in loader.split(missing):
            loader.start_batch(_Batch(loader, self._generation, self._path, batch))


class ThumbnailLoader(QObject):
    thumbnail = Signal(str, int, QImage)  # путь к файлу, номер миниатюры, кадр

    def __init__(
        self,
        ffmpeg: Path,
        parent: QObject | None = None,
        parallel: int = PARALLEL,
        width: int = THUMB_WIDTH,
        limit_bytes: int = cache.DEFAULT_LIMIT_BYTES,
    ) -> None:
        super().__init__(parent)
        self._limit = limit_bytes
        self.ffmpeg = ffmpeg
        self.signals = _Signals()
        self.signals.ready.connect(self._on_ready)
        self.generation = 0
        self.cancel_flag = threading.Event()
        self._parallel = parallel
        self.width = width
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(parallel + 1)  # ещё одно место под поиск готовых на диске
        self._memory: dict[str, QImage] = {}  # ключ кэша файла -> кадр
        self._keys: dict[tuple[str, int], str] = {}
        self._folder: Path | None = None
        self._folder_lock = threading.Lock()

    def prepare_folder(self) -> Path:
        """Папка кэша: создание и чистка по размеру (диск), поэтому вызывается из фона."""
        with self._folder_lock:
            if self._folder is None:
                folder = cache.cache_dir() / "thumbs"
                folder.mkdir(parents=True, exist_ok=True)
                cache.prune(folder, self._limit)
                self._folder = folder
            return self._folder

    def memory_keys(self) -> set[str]:
        return set(self._memory)

    def request(self, path: Path, duration: float, count: int) -> list[QImage | None]:
        """Миниатюры из памяти сразу, остальные (None — заглушка) приходят из фона по сигналу."""
        self.cancel()  # предыдущий клип больше не нужен
        result: list[QImage | None] = []
        identity = cache.file_identity(path)
        for index in range(count):
            key = cache.key_for(identity, index, count, self.width)
            self._keys[(str(path), index)] = key
            result.append(self._memory.get(key))
        if any(image is None for image in result):
            self._pool.start(_Lookup(self, self.generation, path, duration, count))
        return result

    def start_batch(self, batch: "_Batch") -> None:
        self._pool.start(batch)

    def split(self, items: list[tuple[int, float, Path]]) -> list[list[tuple[int, float, Path]]]:
        """Делит недостающие кадры на равные пачки по числу параллельных запусков."""
        if not items:
            return []
        size = -(-len(items) // self._parallel)
        return [items[i : i + size] for i in range(0, len(items), size)]

    def cancel(self) -> None:
        """Прекращает незавершённые пачки (идущий ffmpeg убивается)."""
        self.generation += 1
        self.cancel_flag.set()
        self._pool.clear()
        # ждать завершения нельзя: идущий ffmpeg убивается в своём потоке, а поток интерфейса
        # не должен стоять в очереди за ним (раньше открытие клипа держало окно сотни мс)
        self.cancel_flag = threading.Event()

    def _on_ready(self, path: str, index: int, image: QImage) -> None:
        key = self._keys.get((path, index))
        if key is not None:
            self._memory[key] = image
        self.thumbnail.emit(path, index, image)

    def wait(self) -> None:
        self._pool.waitForDone()
