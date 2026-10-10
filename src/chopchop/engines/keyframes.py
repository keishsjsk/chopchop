"""Ключевые кадры файла через ffprobe: по пакетам, без декодирования, поэтому быстро."""

import subprocess
from pathlib import Path

from chopchop.engines.ffmpeg import find_ffprobe
from chopchop.engines.probe import ProbeError
from chopchop.services.cache import file_key
from chopchop.services.process import no_window_flags
from chopchop.services.profiling import stage

TIMEOUT = 120
MEMO_LIMIT = 32

_memo: dict[str, tuple[float, ...]] = {}


def parse_keyframes(output: str) -> tuple[float, ...]:
    """Времена ключевых кадров из строк «pts_time,flags» (флаг K — ключевой пакет)."""
    times: set[float] = set()
    for line in output.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or "K" not in parts[1]:
            continue
        try:
            times.add(round(float(parts[0]), 6))
        except ValueError:
            continue  # N/A у пакета без метки времени
    return tuple(sorted(times))


def keyframe_args(ffprobe: Path, path: Path) -> list[str]:
    return [
        str(ffprobe),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,flags",
        "-of",
        "csv=print_section=0",
        "-i",
        str(path),
    ]


def read_keyframes(path: Path, ffprobe: Path | None = None) -> tuple[float, ...]:
    """Ключевые кадры по порядку времени; результат запоминается для неизменённого файла."""
    key = file_key(path)
    known = _memo.get(key)
    if known is not None:
        return known
    exe = ffprobe or find_ffprobe()
    if exe is None:
        raise ProbeError("ffprobe not found")
    with stage("video.keyframes"):
        try:
            result = subprocess.run(
                keyframe_args(exe, path),
                capture_output=True,
                timeout=TIMEOUT,
                check=False,
                creationflags=no_window_flags(),
            )
        except subprocess.TimeoutExpired as error:
            raise ProbeError("ffprobe timed out") from error
    if result.returncode != 0:
        raise ProbeError(result.stderr.decode("utf-8", "replace").strip() or "ffprobe failed")
    frames = parse_keyframes(result.stdout.decode("utf-8", "replace"))
    if len(_memo) >= MEMO_LIMIT:
        _memo.pop(next(iter(_memo)))
    _memo[key] = frames
    return frames


def clear_memo() -> None:
    _memo.clear()
