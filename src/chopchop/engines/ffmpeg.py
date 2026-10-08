"""ffmpeg: поиск бинарников и запуск команд с прогрессом и отменой."""

import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chopchop.services.paths import bundled_dirs


def find_binary(name: str, search_dirs: Iterable[Path] | None = None) -> Path | None:
    filename = f"{name}.exe" if sys.platform == "win32" else name
    dirs = bundled_dirs() if search_dirs is None else search_dirs
    for directory in dirs:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    system = shutil.which(name)
    return Path(system) if system else None


def find_ffmpeg(search_dirs: Iterable[Path] | None = None) -> Path | None:
    return find_binary("ffmpeg", search_dirs)


def find_ffprobe(search_dirs: Iterable[Path] | None = None) -> Path | None:
    return find_binary("ffprobe", search_dirs)


_PROGRESS_LINE = re.compile(r"[a-z0-9_]+=\S*")


class FfmpegError(RuntimeError):
    """ffmpeg завершился с ошибкой; в сообщении — последние строки его вывода."""


class ExportCancelled(RuntimeError):
    """Пользователь отменил экспорт."""


@dataclass(frozen=True)
class FfmpegStep:
    args: tuple[str, ...]  # полная команда, включая путь к ffmpeg; запускается без shell
    duration: float  # длительность результата шага, для расчёта прогресса
    output: Path


def parse_progress_line(line: str) -> float | None:
    """Секунды из строки ``out_time_us=...`` вывода ``-progress``; None для остальных строк."""
    key, _, value = line.strip().partition("=")
    if key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(int(value), 0) / 1_000_000
    except ValueError:
        return None  # на старте ffmpeg пишет N/A


def run_step(
    step: FfmpegStep,
    on_progress: Callable[[float], None],
    cancel: threading.Event | None = None,
) -> None:
    """Запускает один шаг; on_progress получает долю 0..1. Список аргументов, без shell."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        list(step.args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        if cancel is not None and cancel.is_set():
            process.terminate()
            process.wait()
            raise ExportCancelled
        seconds = parse_progress_line(line)
        if seconds is not None:
            if step.duration > 0:
                on_progress(min(seconds / step.duration, 1.0))
        elif not _PROGRESS_LINE.fullmatch(line.strip()):
            tail = [*tail[-19:], line.rstrip()]  # не строка прогресса — это сообщение ffmpeg
    if process.wait() != 0:
        raise FfmpegError("\n".join(tail) or f"ffmpeg exited with code {process.returncode}")


def run_steps(
    steps: Sequence[FfmpegStep],
    on_progress: Callable[[float], None],
    cancel: threading.Event | None = None,
) -> None:
    """Выполняет шаги по очереди; общий прогресс считается по длительности шагов."""
    total = sum(step.duration for step in steps) or 1.0
    done = 0.0
    for step in steps:
        base = done

        def report(fraction: float, base: float = base, step: FfmpegStep = step) -> None:
            on_progress(min((base + fraction * step.duration) / total, 1.0))

        run_step(step, report, cancel)
        done += step.duration
        on_progress(min(done / total, 1.0))
