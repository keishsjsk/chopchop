"""ffprobe: сведения о видеофайле (размер, длительность, кодеки, дорожки)."""

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.engines.ffmpeg import find_ffprobe

PROBE_TIMEOUT = 30


class ProbeError(RuntimeError):
    """ffprobe не смог прочитать файл или его нет."""


def _fps(stream: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            value = Fraction(str(stream.get(key, "0/1")))
        except (ValueError, ZeroDivisionError):
            continue
        if value > 0:
            return float(value)
    return 0.0


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return int(round(float(side["rotation"]))) % 360
    try:
        return int(stream.get("tags", {}).get("rotate", 0)) % 360
    except ValueError:
        return 0


def _float(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def parse_probe(data: dict[str, Any]) -> MediaInfo:
    streams: list[dict[str, Any]] = data.get("streams", [])
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    if not videos:
        raise ProbeError("no video stream")
    video = videos[0]
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = _float(data.get("format", {}).get("duration")) or _float(video.get("duration"))
    return MediaInfo(
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        duration=duration,
        fps=_fps(video),
        video_codec=str(video.get("codec_name", "")),
        pix_fmt=str(video.get("pix_fmt", "")),
        rotation=_rotation(video),
        audio=(
            AudioInfo(
                codec=str(audio.get("codec_name", "")),
                sample_rate=int(_float(audio.get("sample_rate"))),
                channels=int(audio.get("channels", 0)),
            )
            if audio
            else None
        ),
    )


def probe(path: Path, ffprobe: Path | None = None) -> MediaInfo:
    exe = ffprobe or find_ffprobe()
    if exe is None:
        raise ProbeError("ffprobe not found")
    args = [
        str(exe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-i",
        str(path),
    ]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=PROBE_TIMEOUT, check=False, creationflags=flags
        )
    except subprocess.TimeoutExpired as error:
        raise ProbeError("ffprobe timed out") from error
    if result.returncode != 0:
        raise ProbeError(result.stderr.decode("utf-8", "replace").strip() or "ffprobe failed")
    try:
        return parse_probe(json.loads(result.stdout))
    except ValueError as error:
        raise ProbeError(str(error)) from error
