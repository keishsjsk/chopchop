"""Операции над открытым файлом: корзина, переименование, свойства, метаданные.

Ничего не удаляется безвозвратно: «Удалить» — только в корзину ОС (`QFile.moveToTrash`, без
сторонних библиотек). Все пути обрабатываются как данные, а не как команды.
"""

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QFile

WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
FORBIDDEN_CHARS = '<>:"/\\|?*'
MAX_NAME = 200
GPS_IFD = 0x8825


class TrashError(OSError):
    """Файл не удалось переместить в корзину (её нет, сетевой диск, нет прав)."""


def move_to_trash(path: Path) -> None:
    """Перемещает файл в корзину; при неудаче ничего не удаляет и бросает `TrashError`."""
    if not path.exists():
        raise TrashError("файл не найден")
    if not QFile.moveToTrash(str(path)):
        raise TrashError("корзина недоступна для этого расположения")
    if path.exists():  # перемещение сообщило об успехе, а файл на месте: считаем неудачей
        raise TrashError("файл остался на месте")


# --- переименование --------------------------------------------------------------------------

# коды ошибок проверки имени: интерфейс подставляет перевод
EMPTY = "empty"
INVALID = "invalid"
RESERVED = "reserved"
TOO_LONG = "too_long"
EXISTS = "exists"
UNCHANGED = "unchanged"


def validate_name(new_stem: str, source: Path) -> str | None:
    """Код ошибки для нового имени без расширения или None, если имя годится."""
    stem = new_stem.strip()
    if not stem:
        return EMPTY
    if any(c in FORBIDDEN_CHARS or ord(c) < 32 for c in stem):
        return INVALID
    if stem.endswith((".", " ")) or stem in (".", ".."):
        return INVALID
    if stem.split(".")[0].upper() in WINDOWS_RESERVED:
        return RESERVED
    if len(stem) + len(source.suffix) > MAX_NAME:
        return TOO_LONG
    target = source.with_name(stem + source.suffix)
    if target == source:
        return UNCHANGED
    if _same_name_exists(target, source):
        return EXISTS
    return None


def _same_name_exists(target: Path, source: Path) -> bool:
    """Занято ли имя: на Windows и macOS регистр букв не различается (но своё имя не в счёт)."""
    if not target.exists():
        return False
    try:
        return not os.path.samefile(target, source)  # то же имя, иной регистр: это он сам
    except OSError:
        return True


def rename_path(source: Path, new_stem: str) -> Path:
    """Переименовывает файл, сохраняя расширение; возвращает новый путь."""
    error = validate_name(new_stem, source)
    if error is not None:
        raise ValueError(error)
    target = source.with_name(new_stem.strip() + source.suffix)
    source.rename(target)
    return target


# --- свойства --------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileFacts:
    name: str
    folder: str
    size_bytes: int
    modified: str


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{int(value)} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} Б"


def file_facts(path: Path) -> FileFacts:
    stat = path.stat()
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
    return FileFacts(path.name, str(path.parent), stat.st_size, modified)


@dataclass(frozen=True)
class MetadataFlags:
    has_exif: bool
    has_gps: bool

    @property
    def any(self) -> bool:
        return self.has_exif or self.has_gps


def photo_metadata(path: Path) -> MetadataFlags:
    """Есть ли в фото EXIF и координаты GPS (читается только заголовок)."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            has_exif = len(exif) > 0
            has_gps = bool(exif.get_ifd(GPS_IFD)) if has_exif else False
    except (OSError, ValueError, SyntaxError):
        return MetadataFlags(False, False)
    return MetadataFlags(has_exif, has_gps)


def photo_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError, SyntaxError):
        return None


def is_windows() -> bool:
    return sys.platform == "win32"
