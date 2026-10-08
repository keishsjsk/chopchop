"""Поиск libmpv. Сам виджет с render API появится на этапе 3."""

import ctypes.util
import sys
from collections.abc import Iterable
from pathlib import Path

from quickedit.services.paths import bundled_dirs

if sys.platform == "win32":
    _LIBRARY_NAMES = ("libmpv-2.dll", "mpv-2.dll")
else:
    _LIBRARY_NAMES = ("libmpv.so.2", "libmpv.so.1", "libmpv.so")


def find_libmpv(search_dirs: Iterable[Path] | None = None) -> Path | None:
    dirs = bundled_dirs() if search_dirs is None else search_dirs
    for directory in dirs:
        for name in _LIBRARY_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    system = ctypes.util.find_library("mpv")
    return Path(system) if system else None
