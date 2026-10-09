"""Какие аппаратные кодеры H.264 есть в сборке ffmpeg (один запуск на сеанс)."""

import subprocess
from functools import lru_cache
from pathlib import Path

from chopchop.engines.video_engine import parse_encoder_names
from chopchop.services.process import no_window_flags

ENCODERS_TIMEOUT = 15


@lru_cache(maxsize=4)
def available_hw_encoders(ffmpeg: Path) -> tuple[str, ...]:
    """Имена вроде h264_nvenc. Наличие в сборке не гарантирует железа: при сбое экспорт
    повторяется на процессоре."""
    try:
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=ENCODERS_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
            creationflags=no_window_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(parse_encoder_names(result.stdout))
