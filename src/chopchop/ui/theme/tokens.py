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
            secondary=accent.secondary,
            on_secondary=accent.on_secondary,
            accent_tint="",  # пересчитывается под новый акцент
        )


@dataclass(frozen=True)
class AccentSet:
    """Акцент одной темы: цвет, его состояния, текст на нём и вторичный цвет семейства."""

    accent: Color
    hover: Color
    pressed: Color
    on_accent: Color
    secondary: Color
    on_secondary: Color
    swatch: Color = ""  # образец в настройках: «лицо» семейства, не обязательно сам акцент

    def sample(self) -> Color:
        return self.swatch or self.accent


def _family(
    accent: Color,
    on_accent: Color,
    secondary: Color,
    on_secondary: Color,
    *,
    light: bool,
    swatch: Color = "",
) -> AccentSet:
    """Состояния акцента считаются от него самого: в светлой теме темнее (текст на нём светлый),
    в тёмной наведение светлее, нажатие чуть темнее, чтобы текст на акценте оставался читаемым."""
    if light:
        hover, pressed = blend("#000000", accent, 0.08), blend("#000000", accent, 0.16)
    else:
        hover, pressed = blend("#FFFFFF", accent, 0.10), blend("#000000", accent, 0.06)
    return AccentSet(accent, hover, pressed, on_accent, secondary, on_secondary, swatch)


ON_ACCENT_LIGHT = "#FFF8F0"
ON_ACCENT_DARK = "#2B0F1A"

# Четыре семейства (палитры-источники: Ember Meadow, Cloud Ruby Harbor, Warm Sunset 6, Cool Coral
# Tide и другие). Светлые акценты затемнены до контраста 4,5:1 с текстом на них, пастельные цвета
# источников стоят у тёмной темы и в образцах. Вторичные цвета — тоже с контрастом 4,5:1 к фону.
ACCENTS: dict[str, dict[str, AccentSet]] = {
    "ember": {  # терракота и шалфей
        "light": _family(
            "#B04F33", ON_ACCENT_LIGHT, "#516D4D", ON_ACCENT_LIGHT, light=True, swatch="#CC704B"
        ),
        "dark": _family(
            "#E8804A", ON_ACCENT_DARK, "#9FC088", ON_ACCENT_DARK, light=False, swatch="#CC704B"
        ),
    },
    "meadow": {  # шалфей и серо-зелёный, вторичный глина
        "light": _family(
            "#5E6F64", ON_ACCENT_LIGHT, "#8A5A4C", ON_ACCENT_LIGHT, light=True, swatch="#9FC088"
        ),
        "dark": _family(
            "#9FC088", ON_ACCENT_DARK, "#C18676", ON_ACCENT_DARK, light=False, swatch="#9FC088"
        ),
    },
    "sunset": {  # красно-оранжевый заката, вторичный золотой
        "light": _family(
            "#B8453F", ON_ACCENT_LIGHT, "#7A612E", ON_ACCENT_LIGHT, light=True, swatch="#C24B4B"
        ),
        "dark": _family(
            "#E4694F", ON_ACCENT_DARK, "#F4C25B", ON_ACCENT_DARK, light=False, swatch="#E8804A"
        ),
    },
    "rose": {  # коралл и розовый, вторичный мятно-бирюзовый; на пастельных заливках текст тёмный
        "light": _family(
            "#B84E55", ON_ACCENT_LIGHT, "#576967", ON_ACCENT_LIGHT, light=True, swatch="#FFA4A4"
        ),
        "dark": _family(
            "#FFA4A4", ON_ACCENT_DARK, "#BADFDB", ON_ACCENT_DARK, light=False, swatch="#FFBDBD"
        ),
    },
}
DEFAULT_ACCENT = "ember"
# прежние названия акцентов из файла настроек
ACCENT_ALIASES = {"orange": "ember", "violet": "meadow", "coral": "rose", "burgundy": "sunset"}


LIGHT = Palette(  # «Ember Cream»: тёплый крем и терракота
    name="light",
    bg="#F8EDE3",
    surface="#FFF8F0",
    surface_raised="#EFE2D2",
    border="#DFD3C3",
    border_strong="#907F74",
    text="#4B2A21",
    text_muted="#766155",
    accent="#B04F33",
    accent_hover="#A2492F",
    accent_pressed="#94422B",
    on_accent="#FFF8F0",
    secondary="#516D4D",
    on_secondary="#FFF8F0",
    danger="#AF413E",
    on_danger="#FFF8F0",
    success="#516D4D",
    scrim=(43, 15, 26, 150),
    focus_ring="#5E6F64",
    shadow="#D0B8A8",
    accent_tint="#F4D9C8",
)

DARK = Palette(  # «Ember Night»: тёплая ночь, терракота и шалфей
    name="dark",
    bg="#241713",
    surface="#2E1F19",
    surface_raised="#3A2A22",
    border="#4A372D",
    border_strong="#83746A",
    text="#F6E6CB",
    text_muted="#BFA993",
    accent="#E8804A",
    accent_hover="#EA8D5C",
    accent_pressed="#DB7746",
    on_accent="#2B0F1A",
    secondary="#9FC088",
    on_secondary="#2B0F1A",
    danger="#E5806F",
    on_danger="#2B0F1A",
    success="#9FC088",
    scrim=(10, 5, 3, 170),
    focus_ring="#F4C25B",
    shadow="#150D0A",
    accent_tint="#4A2E22",
)

PALETTES = {"light": LIGHT, "dark": DARK}


def make_palette(theme: str, accent: str = DEFAULT_ACCENT) -> Palette:
    """Палитра темы («light» или «dark») с выбранным акцентом."""
    base = PALETTES[theme]
    accent = ACCENT_ALIASES.get(accent, accent)
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
