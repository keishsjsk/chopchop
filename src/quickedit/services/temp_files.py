"""Временные файлы приложения: отдельная папка, чистится после экспорта и при запуске."""

import shutil
import tempfile
import time
from pathlib import Path

PREFIX = "quickedit-"
STALE_SECONDS = 3600


def temp_root() -> Path:
    return Path(tempfile.gettempdir())


def new_workspace(root: Path | None = None) -> Path:
    return Path(tempfile.mkdtemp(prefix=PREFIX, dir=root or temp_root()))


def remove_workspace(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_stale(root: Path | None = None, max_age: float = STALE_SECONDS) -> int:
    """Удаляет рабочие папки прошлых запусков (например, после сбоя); возвращает их число."""
    removed = 0
    base = root or temp_root()
    now = time.time()
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.name.startswith(PREFIX) and entry.is_dir():
            try:
                if now - entry.stat().st_mtime > max_age:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    return removed
