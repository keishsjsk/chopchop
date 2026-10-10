"""Пиксельные иконки: целочисленное масштабирование без сглаживания, перекраска токенами темы.

Иконка — текстовый битмап (`icon_data.py`). Рисуется в 16×16 (или 24×24) и увеличивается ровно
в целое число раз методом ближайшего соседа с учётом `devicePixelRatio`: на экране 150% иконка
получает масштаб 2, а не размытые 1,5. Цвет берётся из токенов темы: основной цвет иконки
(`#` в битмапе), акцентный (`a`) и тень на один пиксель вправо и вниз.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from chopchop.ui.theme.icon_data import ICONS_16, ICONS_24
from chopchop.ui.theme.tokens import Palette

GRIDS: dict[int, dict[str, tuple[str, ...]]] = {16: ICONS_16, 24: ICONS_24}

# имена, которые должны быть в наборе (проверяется тестом): нужные редактору и плееру
REQUIRED = (
    "open", "folder", "save", "save_as", "copy", "paste", "undo", "redo", "pause", "play",
    "previous", "next", "volume", "mute", "audio_track", "subtitles", "fullscreen",
    "exit_fullscreen", "settings", "edit", "back_to_view", "crop", "rotate", "flip", "redact",
    "brush", "marker", "arrow", "rectangle", "text", "adjust", "filters", "trim", "split",
    "add_clip", "remove_clip", "zoom_in", "zoom_out", "fit", "close", "check", "warning",
    "info", "trash", "scissors", "drop", "sliders", "step_back", "step_forward",
    "chevron_up", "chevron_down", "chevron_left", "chevron_right", "mark_in", "mark_out",
    "reset_trim", "mode_fast", "mode_precise",
)  # fmt: skip

_cache: dict[tuple[object, ...], QImage] = {}
_qicons: dict[tuple[object, ...], QIcon] = {}

COLOR_ROLES = (
    "text",
    "text_muted",
    "accent",
    "on_accent",
    "secondary",
    "danger",
    "success",
)


def names(size: int = 16) -> list[str]:
    return sorted(GRIDS[size])


def has_size(name: str, size: int) -> bool:
    return name in GRIDS.get(size, {})


def bitmap(name: str, size: int = 16) -> tuple[str, ...]:
    """Текстовый битмап иконки; для размера, которого нет, берётся 16×16."""
    grids = GRIDS.get(size, ICONS_16)
    return grids[name] if name in grids else ICONS_16[name]


def grid_size(name: str, size: int) -> int:
    return size if has_size(name, size) else 16


def render(
    name: str,
    *,
    scale: int = 1,
    size: int = 16,
    color: str = "#000000",
    accent: str | None = None,
    shadow: str | None = None,
) -> QImage:
    """Иконка целым числом пикселей: сетка × scale. shadow=None — без тени."""
    side = grid_size(name, size)
    key = (name, side, scale, color, accent, shadow)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    rows = bitmap(name, side)
    base = QImage(side, side, QImage.Format.Format_ARGB32)
    base.fill(Qt.GlobalColor.transparent)
    main = QColor(color)
    accent_color = QColor(accent) if accent else main
    if shadow is not None:
        shade = QColor(shadow)
        for y, row in enumerate(rows):
            for x, char in enumerate(row):
                if char != "." and x + 1 < side and y + 1 < side:
                    base.setPixelColor(x + 1, y + 1, shade)
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                base.setPixelColor(x, y, main)
            elif char == "a":
                base.setPixelColor(x, y, accent_color)
    image = base.scaled(
        side * scale,
        side * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,  # ближайший сосед: пиксели остаются квадратами
    )
    _cache[key] = image
    return image


def integer_scale(logical: int, ratio: float, grid: int = 16) -> int:
    """Целый масштаб сетки для логического размера на экране с заданным devicePixelRatio."""
    return max(1, round(logical * ratio / grid))


def pixmap(
    name: str,
    palette: Palette,
    *,
    logical: int = 16,
    ratio: float = 1.0,
    role: str = "text",
    shadow: bool = True,
    size: int = 16,
) -> QPixmap:
    """Иконка для рисования: пиксели устройства — целое кратное сетки, ratio учтён в pixmap."""
    side = grid_size(name, size)
    scale = integer_scale(logical, ratio, side)
    color = getattr(palette, role)
    image = render(
        name,
        scale=scale,
        size=side,
        color=color,
        accent=palette.accent,
        shadow=palette.border if shadow else None,
    )
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(side * scale / logical)
    return result


def qicon(
    name: str,
    palette: Palette,
    *,
    logical: int = 16,
    role: str = "text",
    checked_role: str = "on_accent",
    size: int = 16,
) -> QIcon:
    """QIcon для кнопок: обычная, выключенная (приглушённая), нажатая (цвет на акцентной плашке).

    Пиксмапы сделаны для масштабов 1–4, Qt выбирает подходящий под экран. Готовые значки
    запоминаются: редактор создаёт десятки одинаковых кнопок, а сборка значка не бесплатна.
    """
    key = (name, palette, logical, role, checked_role, size)
    cached = _qicons.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    side = grid_size(name, size)
    for ratio in (1.0, 2.0, 3.0, 4.0):
        for mode, state, state_role, with_shadow in (
            (QIcon.Mode.Normal, QIcon.State.Off, role, True),
            (QIcon.Mode.Active, QIcon.State.Off, role, True),
            (QIcon.Mode.Disabled, QIcon.State.Off, "text_muted", False),
            (QIcon.Mode.Normal, QIcon.State.On, checked_role, False),
            (QIcon.Mode.Active, QIcon.State.On, checked_role, False),
        ):
            icon.addPixmap(
                pixmap(
                    name,
                    palette,
                    logical=logical,
                    ratio=ratio,
                    role=state_role,
                    shadow=with_shadow,
                    size=side,
                ),
                mode,
                state,
            )
    _qicons[key] = icon
    return icon


def clear_cache() -> None:
    _cache.clear()
    _qicons.clear()
