"""Запуск внешних программ (ffmpeg, ffprobe)."""

import subprocess
import sys


def no_window_flags() -> int:
    """Флаги subprocess: на Windows не мигать окном консоли при запуске ffmpeg."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
