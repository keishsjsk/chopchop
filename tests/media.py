"""Генерация тестовых роликов через ffmpeg (testsrc и sine) для интеграционных тестов."""

import atexit
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from quickedit.engines.ffmpeg import find_ffmpeg, find_ffprobe

FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()
HAS_FFMPEG = FFMPEG is not None and FFPROBE is not None


_cache_dir: Path | None = None
_cache: dict[tuple[object, ...], Path] = {}


def _cached(key: tuple[object, ...]) -> Path | None:
    return _cache.get(key)


def _store(key: tuple[object, ...], path: Path) -> None:
    """Запоминает готовый ролик: генерация через ffmpeg — самая долгая часть тестов."""
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = Path(tempfile.mkdtemp(prefix="quickedit-test-media-"))
        atexit.register(shutil.rmtree, _cache_dir, ignore_errors=True)
    stored = _cache_dir / f"{len(_cache)}{path.suffix}"
    shutil.copyfile(path, stored)
    _cache[key] = stored


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=120)


def make_video(
    path: Path,
    seconds: int = 6,
    size: tuple[int, int] = (320, 240),
    fps: int = 25,
    audio: bool = True,
    frequency: int = 440,
    title: str | None = None,
) -> Path:
    """Ролик с ключевым кадром каждую секунду, чтобы быстрая обрезка по секундам была точной."""
    assert FFMPEG is not None
    key = ("video", seconds, size, fps, audio, frequency, title)
    ready = _cached(key)
    if ready is not None:
        shutil.copyfile(ready, path)
        return path
    args = [str(FFMPEG), "-y", "-loglevel", "error"]
    args += ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size[0]}x{size[1]}:rate={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}"]
    args += ["-c:v", "libx264", "-g", str(fps), "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    if audio:
        args += ["-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest"]
    if title:
        args += ["-metadata", f"title={title}"]
    args.append(str(path))
    run(args)
    _store(key, path)
    return path


def make_wav(path: Path, seconds: int = 3, frequency: int = 880) -> Path:
    assert FFMPEG is not None
    run(
        [str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi"]
        + ["-i", f"sine=frequency={frequency}:duration={seconds}", str(path)]
    )
    return path


def mean_volume(path: Path) -> float:
    """Средняя громкость звука в дБ по volumedetect."""
    assert FFMPEG is not None
    result = subprocess.run(
        [str(FFMPEG), "-nostdin", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    assert match, result.stderr
    return float(match.group(1))
