"""Миниатюры для полосы обрезки: по одному кадру, в фоне, с кэшем на время сессии."""

import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from chopchop.engines.video_engine import thumbnail_args
from chopchop.services.process import no_window_flags

THUMB_TIMEOUT = 20


def extract_thumbnail(ffmpeg: Path, path: Path, at: float) -> bytes:
    """PNG-кадр на заданной секунде; пустые байты, если кадр достать не удалось."""
    flags = no_window_flags()
    try:
        result = subprocess.run(
            thumbnail_args(ffmpeg, path, at),
            capture_output=True,
            timeout=THUMB_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return b""
    return result.stdout if result.returncode == 0 else b""


class _Signals(QObject):
    ready = Signal(str, int, QImage)


class _Job(QRunnable):
    def __init__(self, ffmpeg: Path, path: Path, index: int, at: float, signals: _Signals) -> None:
        super().__init__()
        self._args = (ffmpeg, path, index, at)
        self._signals = signals

    def run(self) -> None:
        ffmpeg, path, index, at = self._args
        data = extract_thumbnail(ffmpeg, path, at)
        image = QImage.fromData(data) if data else QImage()
        if not image.isNull():
            self._signals.ready.emit(str(path), index, image)


class ThumbnailLoader(QObject):
    thumbnail = Signal(str, int, QImage)  # путь к файлу, номер миниатюры, кадр

    def __init__(self, ffmpeg: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ffmpeg = ffmpeg
        self._signals = _Signals()
        self._signals.ready.connect(self._on_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._cache: dict[tuple[str, int], QImage] = {}
        self._requested: set[tuple[str, int]] = set()

    def request(self, path: Path, duration: float, count: int) -> list[QImage | None]:
        """Возвращает уже готовые миниатюры, недостающие загружаются в фоне."""
        result: list[QImage | None] = []
        for index in range(count):
            key = (str(path), index)
            result.append(self._cache.get(key))
            if key not in self._cache and key not in self._requested:
                self._requested.add(key)
                # середина каждого отрезка, чтобы не попасть на чёрный первый кадр
                at = duration * (index + 0.5) / count
                self._pool.start(_Job(self._ffmpeg, path, index, at, self._signals))
        return result

    def _on_ready(self, path: str, index: int, image: QImage) -> None:
        self._cache[(path, index)] = image
        self.thumbnail.emit(path, index, image)

    def wait(self) -> None:
        self._pool.waitForDone()
