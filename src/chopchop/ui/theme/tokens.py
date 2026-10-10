"""Токены оформления: цвета двух тем, сетка отступов, размеры и тайминги.

Любой цвет, отступ и размер в интерфейсе берётся отсюда. Пары цветов, которые встречаются
вместе, проверены на контраст тестом `tests/ui/test_theme_tokens.py` (текст 4,5:1, элементы
управления 3:1).
"""

from dataclasses import dataclass, replace

# --- сетка и размеры ----------------------------------------------------------------------

SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_6 = 4, 8, 12, 16, 24  # сетка 4/8/12/16/24
MIN_HIT = 32  # минимальная область нажатия
BUTTON_HEIGHT = 40  # основные кнопки
RAIL_BUTTON = 40  # кнопка левой рейки инструментов
ICON_SMALL = 16  # сетка пиксельных иконок
ICON_LARGE = 24
PIXEL_STEP = 2  # размер «пикселя» рамок и теней (ступенька угла)
BORDER_WIDTH = 2
SHADOW_OFFSET = 4  # жёсткая тень без размытия
FOCUS_GAP = 2  # зазор между элементом и кольцом фокуса
DIM_ALPHA = 153  # затемнение вне рамки кадрирования: 60%
HANDLE_SIZE = 8  # видимая ручка рамки
HANDLE_HIT = 24  # область захвата ручки: не меньше 16
SNAP_PX = 6  # привязка к краям и центру кадра

# --- плеер: размеры по умолчанию при масштабе 100% -----------------------------------------
PLAYER_BAR_H = 40  # нижняя панель вместе с жёсткой тенью
PLAYER_BAR_FS_H = 36  # в полном экране
PLAYER_BUTTON = 28  # кнопки панели
PLAYER_BAR_MAX_W = 560
PLAYER_TOP_H = 32  # верхняя панель с названием файла
UI_ICON = 18  # значки интерфейса видны размером 16-20 px; точный размер по devicePixelRatio
UI_FONT_PX = 12  # подписи и время: 12-13 px

# --- оболочка редактора --------------------------------------------------------------------
TOP_BAR_H = 40  # верхняя панель редактора
CONTEXT_H = 36  # панель параметров инструмента
CONTEXT_CONTROL_H = 28  # кнопки и поля внутри неё, вместе с рамкой
ICON_BUTTON = 32  # кнопка со значком (транспорт, панели)
SMALL_BUTTON = 28  # мелкие кнопки: удалить эффект, стрелки
TRANSPORT_H = 36
STATUS_H = 24
RAIL_W = 56
CLIP_STRIP_H = 40  # полоса клипов с одним клипом
CLIP_STRIP_MAX = 128  # предел роста полосы при многих клипах
TRIM_MIN_H = 88  # полоса блоков: линейка и миниатюры
TRIM_MAX_H = 200
TRIM_DEFAULT_H = 112
TOGGLE_W, TOGGLE_H = 40, 20  # пиксельный тумблер

# --- тайминги, мс ---------------------------------------------------------------------------

HOVER_MS = 100
PANEL_MS = 150  # панели: 120-180 мс, ease-out
FADE_MS = 150
TOOLTIP_DELAY_MS = 400

Color = str  # "#rrggbb"

# чёрный и белый для обводок поверх фото и видео: они должны читаться на любой картинке
OVERLAY_DARK = (0, 0, 0)
OVERLAY_LIGHT = (255, 255, 255)
RGBA = tuple[int, int, int, int]


TINT_AMOUNT = 0.2  # доля акцента в тонировке выбранного сегмента


def blend(foreground: Color, background: Color, amount: float) -> Color:
    """Смесь двух цветов: amount — доля foreground."""
    parts = []
    for index in (1, 3, 5):
        top = int(foreground[index : index + 2], 16)
        bottom = int(background[index : index + 2], 16)
        parts.append(round(top * amount + bottom * (1 - amount)))
    return "#{:02x}{:02x}{:02x}".format(*parts)


@dataclass(frozen=True)
class Palette:
    """Цвета одной темы. Обычные цвета — «#rrggbb», scrim — с прозрачностью."""

    name: str
    bg: Color
    surface: Color
    surface_raised: Color
    border: Color  # мягкая разделительная линия (декор, без требований к контрасту)
    border_strong: Color  # рамка полей и кнопок: контраст 3:1
    text: Color
    text_muted: Color
    accent: Color
    accent_hover: Color
    accent_pressed: Color
    on_accent: Color
    secondary: Color
    on_secondary: Color
    danger: Color
    on_danger: Color
    success: Color
    scrim: RGBA
    focus_ring: Color
    shadow: Color  # жёсткая тень рамок
    accent_tint: Color = ""  # лёгкая тонировка выбранного сегмента: акцент поверх поверхности

    def __post_init__(self) -> None:
        if not self.accent_tint:
            object.__setattr__(
                self, "accent_tint", blend(self.accent, self.surface_raised, TINT_AMOUNT)
            )

    def with_accent(self, accent: "AccentSet") -> "Palette":
        return replace(
            self,
            accent=accent.accent,
            accent_hover=accent.hover,
            accent_pressed=accent.pressed,
            on_accent=accent.on_accent,
            accent_tint="",  # пересчитывается под новый акцент
        )


@dataclass(frozen=True)
class AccentSet:
    accent: Color
    hover: Color
    pressed: Color
    on_accent: Color


LIGHT = Palette(
    name="light",
    bg="#F6EDDF",
    surface="#FFFBF2",
    surface_raised="#FFFFFF",
    border="#D9C7AE",
    border_strong="#98827A",
    text="#3E2230",
    text_muted="#6F5B65",
    accent="#CE6C2A",
    accent_hover="#DA7A38",
    accent_pressed="#C96932",
    on_accent="#2A1020",
    secondary="#7F52A0",
    on_secondary="#FFFFFF",
    danger="#AE4C46",
    on_danger="#FFFFFF",
    success="#2E7A47",
    scrim=(42, 16, 32, 150),
    focus_ring="#5B3A8C",
    shadow="#C9B496",
)

DARK = Palette(
    name="dark",
    bg="#1E1820",
    surface="#2A2230",
    surface_raised="#352B3C",
    border="#4A3D52",
    border_strong="#8E8188",
    text="#F3E8D8",
    text_muted="#B8A9B5",
    accent="#F09050",
    accent_hover="#F8A468",
    accent_pressed="#D97A3A",
    on_accent="#1E1820",
    secondary="#B58AD6",
    on_secondary="#1E1820",
    danger="#F2857C",
    on_danger="#1E1820",
    success="#7BC38E",
    scrim=(10, 6, 12, 170),
    focus_ring="#E8C9FF",
    shadow="#120D14",
)

PALETTES = {"light": LIGHT, "dark": DARK}

# Акценты: у каждой темы свой вариант, чтобы цвет читался на её фоне
ACCENTS: dict[str, dict[str, AccentSet]] = {
    "orange": {
        "light": AccentSet("#CE6C2A", "#DA7A38", "#C96932", "#2A1020"),
        "dark": AccentSet("#F09050", "#F8A468", "#D97A3A", "#1E1820"),
    },
    "violet": {
        "light": AccentSet("#7F52A0", "#6F4590", "#603A80", "#FFFFFF"),
        "dark": AccentSet("#B58AD6", "#C49BE2", "#A276C6", "#1E1820"),
    },
    "coral": {
        "light": AccentSet("#C34A44", "#B4413B", "#A23A35", "#FFFFFF"),
        "dark": AccentSet("#F2857C", "#F9968E", "#DF6F66", "#1E1820"),
    },
    "burgundy": {
        "light": AccentSet("#8E2F4A", "#7C2640", "#6B1F37", "#FFFFFF"),
        "dark": AccentSet("#E07A98", "#EA8DA9", "#CB6684", "#1E1820"),
    },
}
DEFAULT_ACCENT = "orange"


def make_palette(theme: str, accent: str = DEFAULT_ACCENT) -> Palette:
    """Палитра темы («light» или «dark») с выбранным акцентом."""
    base = PALETTES[theme]
    family = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])
    return base.with_accent(family[theme])


# --- контраст ---------------------------------------------------------------------------------


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color: Color) -> float:
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def contrast(first: Color, second: Color) -> float:
    """Коэффициент контраста WCAG от 1 до 21."""
    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)
