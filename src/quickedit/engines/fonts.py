"""Поиск шрифта с кириллицей для подписей на фото."""

from functools import lru_cache

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
