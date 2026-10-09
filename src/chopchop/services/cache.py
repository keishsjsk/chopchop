"""Дисковый кэш приложения (миниатюры): в папке кэша ОС, с ограничением размера."""

import hashlib
import os
from pathlib import Path

CACHE_ENV = "CHOPCHOP_CACHE_DIR"
DEFAULT_LIMIT_BYTES = 200 * 1024 * 1024


def cache_dir() -> Path:
    """Папка кэша; CHOPCHOP_CACHE_DIR переопределяет её (тесты и бенчмарки)."""
    override = os.environ.get(CACHE_ENV)
    if override:
        base = Path(override)
    else:
        from PySide6.QtCore import QStandardPaths

        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        base = Path(location or Path.home() / ".cache" / "chopchop")
    base.mkdir(parents=True, exist_ok=True)
    return base


def file_key(path: Path, *parts: object) -> str:
    """Ключ кэша: файл (путь, размер, время изменения) и параметры; при правке файла меняется."""
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(path)
    text = "|".join([identity, *map(str, parts)])
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def prune(folder: Path, max_bytes: int = DEFAULT_LIMIT_BYTES) -> int:
    """Удаляет самые старые файлы, пока папка больше лимита; возвращает число удалённых."""
    entries: list[tuple[float, int, Path]] = []
    try:
        for entry in folder.iterdir():
            if entry.is_file():
                stat = entry.stat()
                entries.append((stat.st_mtime, stat.st_size, entry))
    except OSError:
        return 0
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, entry in sorted(entries):
        if total <= max_bytes:
            break
        try:
            entry.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    return removed


def clear(folder: Path) -> int:
    return prune(folder, 0)
