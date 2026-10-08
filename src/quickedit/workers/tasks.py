"""Запуск тяжёлых функций в фоне: результат возвращается в потоке интерфейса."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)


class _Job(QRunnable):
    def __init__(self, job_id: int, fn: Callable[[], object], signals: _Signals) -> None:
        super().__init__()
        self._job_id = job_id
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as error:
            self._signals.failed.emit(self._job_id, str(error) or type(error).__name__)
        else:
            self._signals.done.emit(self._job_id, result)


class TaskRunner(QObject):
    def __init__(self, parent: QObject | None = None, threads: int = 2) -> None:
        super().__init__(parent)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)
        self._callbacks: dict[int, tuple[Callable[[Any], None], Callable[[str], None] | None]] = {}
        self._next_id = 0

    def run(
        self,
        fn: Callable[[], object],
        on_done: Callable[[Any], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._next_id += 1
        self._callbacks[self._next_id] = (on_done, on_error)
        self._pool.start(_Job(self._next_id, fn, self._signals))

    def wait(self) -> None:
        self._pool.waitForDone()

    def _on_done(self, job_id: int, result: object) -> None:
        on_done, _ = self._callbacks.pop(job_id)
        on_done(result)

    def _on_failed(self, job_id: int, message: str) -> None:
        _, on_error = self._callbacks.pop(job_id)
        if on_error is not None:
            on_error(message)
