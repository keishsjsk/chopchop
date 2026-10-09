"""Профилирование: время стадий и сторож зависаний цикла событий (CHOPCHOP_PROFILE=1)."""

import logging
import os
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger("chopchop.profile")

STALL_MS = 50.0  # дольше этого цикл событий считается зависшим
HEARTBEAT_MS = 10

_enabled = os.environ.get("CHOPCHOP_PROFILE", "") not in ("", "0")
_records: list[tuple[str, float]] = []


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    """Включает профилирование из кода (бенчмарки и тесты) независимо от переменной среды."""
    global _enabled
    _enabled = value


def records() -> list[tuple[str, float]]:
    return list(_records)


def clear() -> None:
    _records.clear()


def record(name: str, milliseconds: float) -> None:
    if not _enabled:
        return
    _records.append((name, milliseconds))
    log.info("%-28s %8.2f ms", name, milliseconds)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Замеряет время блока; при выключенном профилировании ничего не стоит."""
    if not _enabled:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - started) * 1000)


def summary() -> dict[str, tuple[int, float, float]]:
    """Стадия -> (число замеров, среднее, максимум) в миллисекундах."""
    grouped: dict[str, list[float]] = {}
    for name, value in _records:
        grouped.setdefault(name, []).append(value)
    return {n: (len(v), sum(v) / len(v), max(v)) for n, v in grouped.items()}


def setup_logging() -> None:
    """Вывод замеров в stderr; вызывается при запуске, если профилирование включено."""
    if not _enabled:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[profile] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class LoopWatchdog:
    """Сторож: поток-наблюдатель замечает, что цикл событий не отвечал дольше порога.

    Поток интерфейса раз в HEARTBEAT_MS отмечает время (QTimer); наблюдатель сравнивает
    отметку с часами и при зависании пишет в лог, где именно стоит поток интерфейса.
    """

    def __init__(self, threshold_ms: float = STALL_MS) -> None:
        self._threshold = threshold_ms / 1000
        self._beat = time.perf_counter()
        self._stop = threading.Event()
        self._main_id = threading.get_ident()
        self._thread = threading.Thread(target=self._watch, name="chopchop-watchdog", daemon=True)
        self._timer: object | None = None
        self.stalls: list[float] = []

    def start(self) -> None:
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setInterval(HEARTBEAT_MS)
        timer.timeout.connect(self._tick)
        timer.start()
        self._timer = timer
        self._beat = time.perf_counter()
        self._main_id = threading.get_ident()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        timer = self._timer
        if timer is not None:
            timer.stop()  # type: ignore[attr-defined]
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _tick(self) -> None:
        self._beat = time.perf_counter()

    def _watch(self) -> None:
        reported = 0.0
        while not self._stop.wait(HEARTBEAT_MS / 1000):
            beat = self._beat
            late = time.perf_counter() - beat
            if late > self._threshold and beat != reported:
                reported = beat
                self.stalls.append(late * 1000)
                frame = sys._current_frames().get(self._main_id)
                where = "".join(traceback.format_stack(frame, limit=6)) if frame else ""
                log.warning("event loop stalled %.0f ms\n%s", late * 1000, where)
