"""Экспорт видео в фоне: прогресс, отмена, удаление недописанного файла и временных файлов."""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from chopchop.engines.ffmpeg import ExportCancelled, run_steps
from chopchop.engines.video_engine import ExportPlan
from chopchop.services.temp_files import remove_workspace


class _Signals(QObject):
    progress = Signal(float)
    finished = Signal(Path)
    failed = Signal(str)
    cancelled = Signal()


class _Job(QRunnable):
    def __init__(
        self, plan: ExportPlan, workdir: Path, signals: _Signals, cancel: threading.Event
    ) -> None:
        super().__init__()
        self._plan = plan
        self._workdir = workdir
        self._signals = signals
        self._cancel = cancel

    def run(self) -> None:
        try:
            run_steps(self._plan.steps, self._signals.progress.emit, self._cancel)
        except ExportCancelled:
            self._plan.dest.unlink(missing_ok=True)  # недописанный файл не оставляем
            self._signals.cancelled.emit()
        except Exception as error:
            self._plan.dest.unlink(missing_ok=True)
            self._signals.failed.emit(str(error) or type(error).__name__)
        else:
            self._signals.finished.emit(self._plan.dest)
        finally:
            remove_workspace(self._workdir)


class ExportWorker(QObject):
    progress = Signal(float)
    finished = Signal(Path)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._signals = _Signals()
        self._signals.progress.connect(self.progress)
        self._signals.finished.connect(self.finished)
        self._signals.failed.connect(self.failed)
        self._signals.cancelled.connect(self.cancelled)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cancel = threading.Event()

    def start(self, plan: ExportPlan, workdir: Path) -> None:
        self._cancel = threading.Event()
        self._pool.start(_Job(plan, workdir, self._signals, self._cancel))

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self) -> None:
        self._pool.waitForDone()
