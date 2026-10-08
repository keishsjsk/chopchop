"""Поиск бинарников ffmpeg и ffprobe: сначала рядом с программой, затем в системе."""

import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

from quickedit.services.paths import bundled_dirs


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
