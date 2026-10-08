"""Поиск и загрузка libmpv, создание изолированного экземпляра mpv."""

import ctypes.util
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

from chopchop.services.paths import bundled_dirs
from chopchop.services.settings import PlayerPrefs

if sys.platform == "win32":
    _LIBRARY_NAMES = ("libmpv-2.dll", "mpv-2.dll")
else:
    _LIBRARY_NAMES = ("libmpv.so.2", "libmpv.so.1", "libmpv.so")


class MpvUnavailableError(RuntimeError):
    """libmpv не найдена или не загружается."""


def find_libmpv(search_dirs: Iterable[Path] | None = None) -> Path | None:
    dirs = bundled_dirs() if search_dirs is None else search_dirs
    for directory in dirs:
        for name in _LIBRARY_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    system = ctypes.util.find_library("mpv")
    return Path(system) if system else None


def load_mpv_module() -> ModuleType:
    """Импортирует python-mpv; тяжёлая библиотека подключается только при первом видео."""
    lib = find_libmpv()
    if lib is None:
        raise MpvUnavailableError("libmpv not found")
    if sys.platform == "win32" and lib.is_absolute():
        # python-mpv ищет DLL в PATH, поэтому папку с нашей копией ставим первой
        os.environ["PATH"] = str(lib.parent) + os.pathsep + os.environ.get("PATH", "")
    original_find_library = ctypes.util.find_library
    if sys.platform != "win32" and lib.is_absolute() and lib.is_file():
        # python-mpv на Linux сам ищет libmpv в системе; подсовываем библиотеку из сборки
        def find_bundled(name: str) -> str | None:
            return str(lib) if name == "mpv" else original_find_library(name)

        ctypes.util.find_library = find_bundled
    try:
        import mpv
    except OSError as error:
        raise MpvUnavailableError(str(error)) from error
    finally:
        ctypes.util.find_library = original_find_library
    module: ModuleType = mpv
    return module


def create_mpv(module: ModuleType, prefs: PlayerPrefs) -> Any:
    """Изолированный mpv: без пользовательских конфигов, скриптов, сети и своего интерфейса."""
    options: dict[str, Any] = {
        "vo": "libmpv",
        "config": False,
        "load_scripts": False,
        "load_auto_profiles": False,
        "ytdl": False,
        "terminal": False,
        "input_default_bindings": False,
        "input_vo_keyboard": False,
        "osc": False,
        "osd_level": 0,
        "hwdec": "auto-safe",
        "keep_open": True,
        "sub_auto": "fuzzy",
        "volume_max": 130,
        # полупрозрачная чёрная обводка, чтобы текст читался и на белом фоне
        "sub_border_size": 4,
        "sub_border_color": "#B8000000",
        "sub_font_size": prefs.sub_font_size,
        "sub_margin_y": prefs.sub_margin,
    }
    if prefs.audio_langs:
        options["alang"] = prefs.audio_langs
    if prefs.sub_langs:
        options["slang"] = prefs.sub_langs
    try:
        return module.MPV(**options)
    except Exception as error:
        raise MpvUnavailableError(str(error)) from error
