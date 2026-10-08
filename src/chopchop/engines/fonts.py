"""Поиск шрифта с кириллицей для подписей на фото."""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_CANDIDATES = (
    "arial.ttf",
    "segoeui.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "FreeSans.ttf",
)


@lru_cache(maxsize=64)
def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=1)
def find_font_path() -> Path | None:
    """Файл шрифта с кириллицей для drawtext в ffmpeg; None, если системный шрифт не найден."""
    for name in _CANDIDATES:
        try:
            font = ImageFont.truetype(name, 12)
        except OSError:
            continue
        path = Path(str(getattr(font, "path", "")))
        if path.is_file():
            return path
    return None
