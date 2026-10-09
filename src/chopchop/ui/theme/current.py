"""Активная палитра: самостоятельно рисующие виджеты берут цвета отсюда при перерисовке."""

from chopchop.ui.theme.tokens import LIGHT, Palette

_palette: Palette = LIGHT
_pixel_titles = True
_compact = False


def palette() -> Palette:
    return _palette


def set_palette(value: Palette) -> None:
    global _palette
    _palette = value


def pixel_titles() -> bool:
    return _pixel_titles


def set_pixel_titles(value: bool) -> None:
    global _pixel_titles
    _pixel_titles = value


def compact() -> bool:
    return _compact


def set_compact(value: bool) -> None:
    global _compact
    _compact = value
