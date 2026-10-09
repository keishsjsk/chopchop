"""Оформление субтитров: модель, встроенные пресеты и перевод в свойства mpv.

Чистый Python без Qt и mpv. Одно оформление действует на обе строки субтитров: mpv хранит
стиль в общих свойствах `sub-*`, отдельного набора для второй дорожки у него нет (отдельно
настраиваются только позиция `secondary-sub-pos` и задержка).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any, Literal, cast

from chopchop.core.tr_marks import QT_TRANSLATE_NOOP

AlignX = Literal["left", "center", "right"]
AlignY = Literal["top", "center", "bottom"]
AssMode = Literal["file", "scale", "mine"]

ALIGN_X = ("left", "center", "right")
ALIGN_Y = ("top", "center", "bottom")
# «Оформление из файла или моё» → sub-ass-override: no, scale, force
ASS_MODES: tuple[tuple[AssMode, str, str], ...] = (
    ("file", "no", QT_TRANSLATE_NOOP("SubtitleStyle", "Как в файле")),
    ("scale", "scale", QT_TRANSLATE_NOOP("SubtitleStyle", "Как в файле, мой масштаб")),
    ("mine", "force", QT_TRANSLATE_NOOP("SubtitleStyle", "Моё оформление")),
)
# кодировки текстовых субтитров (sub-codepage); «UTF-8, затем CP1251» удобно для русских файлов
CODEPAGES: tuple[tuple[str, str], ...] = (
    ("auto", QT_TRANSLATE_NOOP("SubtitleStyle", "Автоопределение")),
    ("utf-8", "UTF-8"),
    ("utf-8:cp1251", QT_TRANSLATE_NOOP("SubtitleStyle", "UTF-8, иначе CP1251")),
    ("cp1251", QT_TRANSLATE_NOOP("SubtitleStyle", "CP1251 (кириллица, Windows)")),
    ("koi8-r", QT_TRANSLATE_NOOP("SubtitleStyle", "KOI8-R (кириллица)")),
    ("koi8-u", QT_TRANSLATE_NOOP("SubtitleStyle", "KOI8-U (украинская)")),
    ("cp866", QT_TRANSLATE_NOOP("SubtitleStyle", "CP866 (кириллица, DOS)")),
    ("cp1252", QT_TRANSLATE_NOOP("SubtitleStyle", "CP1252 (Западная Европа)")),
    ("cp1250", QT_TRANSLATE_NOOP("SubtitleStyle", "CP1250 (Центральная Европа)")),
    ("iso-8859-1", "ISO-8859-1"),
    ("iso-8859-2", "ISO-8859-2"),
    ("iso-8859-5", QT_TRANSLATE_NOOP("SubtitleStyle", "ISO-8859-5 (кириллица)")),
    ("iso-8859-15", "ISO-8859-15"),
    ("cp1253", QT_TRANSLATE_NOOP("SubtitleStyle", "CP1253 (греческая)")),
    ("cp1254", QT_TRANSLATE_NOOP("SubtitleStyle", "CP1254 (турецкая)")),
    ("cp932", QT_TRANSLATE_NOOP("SubtitleStyle", "CP932 (японская)")),
    ("gbk", QT_TRANSLATE_NOOP("SubtitleStyle", "GBK (китайская)")),
    ("big5", QT_TRANSLATE_NOOP("SubtitleStyle", "Big5 (китайская)")),
    ("euc-kr", QT_TRANSLATE_NOOP("SubtitleStyle", "EUC-KR (корейская)")),
)
# картиночные субтитры (Blu-ray, DVD, DVB): стили к ним неприменимы
IMAGE_CODECS = frozenset(
    {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "dvb_subtitle", "dvbsub", "xsub"}
)

SIZE_RANGE = (10, 150)
OUTLINE_RANGE = (0.0, 10.0)
SHADOW_RANGE = (0.0, 10.0)
SPACING_RANGE = (0, 60)
MARGIN_RANGE = (0, 300)
POS_RANGE = (0, 100)
SCALE_RANGE = (0.5, 3.0)


def is_image_codec(codec: str | None) -> bool:
    return bool(codec) and codec.lower() in IMAGE_CODECS  # type: ignore[union-attr]


@dataclass(frozen=True)
class SubtitleStyle:
    font: str = ""  # пусто — шрифт по умолчанию (sans-serif)
    font_size: int = 55  # как в mpv: размер при высоте кадра 720, дальше масштабируется с видео
    bold: bool = False
    italic: bool = False
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_size: float = 3.0
    shadow_color: str = "#000000"
    shadow_offset: float = 0.0
    back_enabled: bool = False
    back_color: str = "#000000"
    back_opacity: int = 70  # процентов непрозрачности подложки
    line_spacing: int = 0
    margin_y: int = 22
    margin_x: int = 19
    align_x: AlignX = "center"
    align_y: AlignY = "bottom"
    pos: int = 100  # положение по высоте, процентов от верха (для картинок тоже)
    scale: float = 1.0
    ass_mode: AssMode = "scale"

    def with_values(self, **changes: object) -> "SubtitleStyle":
        return clamp(replace(self, **changes))  # type: ignore[arg-type]


def _hex(value: object, default: str) -> str:
    text = str(value).strip()
    if len(text) == 7 and text[0] == "#":
        try:
            int(text[1:], 16)
        except ValueError:
            return default
        return text.upper()
    return default


def _number(value: object, low: float, high: float, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def clamp(style: SubtitleStyle) -> SubtitleStyle:
    """Значения в допустимых пределах: импортированный пресет не должен ломать плеер."""
    default = SubtitleStyle()
    return SubtitleStyle(
        font=str(style.font).strip(),
        font_size=round(_number(style.font_size, *SIZE_RANGE, default.font_size)),
        bold=bool(style.bold),
        italic=bool(style.italic),
        color=_hex(style.color, default.color),
        outline_color=_hex(style.outline_color, default.outline_color),
        outline_size=round(_number(style.outline_size, *OUTLINE_RANGE, default.outline_size), 1),
        shadow_color=_hex(style.shadow_color, default.shadow_color),
        shadow_offset=round(_number(style.shadow_offset, *SHADOW_RANGE, default.shadow_offset), 1),
        back_enabled=bool(style.back_enabled),
        back_color=_hex(style.back_color, default.back_color),
        back_opacity=round(_number(style.back_opacity, 0, 100, default.back_opacity)),
        line_spacing=round(_number(style.line_spacing, *SPACING_RANGE, default.line_spacing)),
        margin_y=round(_number(style.margin_y, *MARGIN_RANGE, default.margin_y)),
        margin_x=round(_number(style.margin_x, *MARGIN_RANGE, default.margin_x)),
        align_x=style.align_x if style.align_x in ALIGN_X else default.align_x,
        align_y=style.align_y if style.align_y in ALIGN_Y else default.align_y,
        pos=round(_number(style.pos, *POS_RANGE, default.pos)),
        scale=round(_number(style.scale, *SCALE_RANGE, default.scale), 2),
        ass_mode=style.ass_mode if style.ass_mode in {m for m, _, _ in ASS_MODES} else "scale",
    )


# --- встроенные пресеты ---------------------------------------------------------------------

STANDARD = QT_TRANSLATE_NOOP("SubtitleStyle", "Стандарт")
CINEMA = QT_TRANSLATE_NOOP("SubtitleStyle", "Кино")
CONTRAST = QT_TRANSLATE_NOOP("SubtitleStyle", "Высокий контраст")
LARGE = QT_TRANSLATE_NOOP("SubtitleStyle", "Крупно")

BUILTIN: dict[str, SubtitleStyle] = {
    STANDARD: SubtitleStyle(),
    CINEMA: SubtitleStyle(
        font_size=48,
        color="#F2E7C9",
        outline_size=2.0,
        shadow_color="#000000",
        shadow_offset=2.0,
        italic=False,
        margin_y=34,
    ),
    CONTRAST: SubtitleStyle(
        font_size=62,
        bold=True,
        color="#FFFF00",
        outline_size=5.0,
        back_enabled=True,
        back_color="#000000",
        back_opacity=85,
        line_spacing=4,
    ),
    LARGE: SubtitleStyle(
        font_size=80, bold=True, outline_size=4.0, shadow_offset=2.0, margin_y=40, line_spacing=6
    ),
}


# --- свойства mpv ---------------------------------------------------------------------------


def _alpha_color(color: str, percent: int) -> str:
    alpha = round(percent / 100 * 255)
    return f"#{alpha:02X}{color[1:]}"


def to_mpv(style: SubtitleStyle) -> dict[str, object]:
    """Имена свойств mpv (с подчёркиваниями, как у python-mpv) и их значения."""
    mode = next(code for key, code, _ in ASS_MODES if key == style.ass_mode)
    values: dict[str, object] = {
        "sub_font_size": style.font_size,
        "sub_bold": style.bold,
        "sub_italic": style.italic,
        "sub_color": _alpha_color(style.color, 100),
        "sub_border_color": _alpha_color(style.outline_color, 100),
        "sub_border_size": style.outline_size,
        "sub_shadow_color": _alpha_color(style.shadow_color, 100),
        "sub_shadow_offset": style.shadow_offset,
        "sub_back_color": _alpha_color(style.back_color, style.back_opacity),
        "sub_border_style": "opaque-box" if style.back_enabled else "outline-and-shadow",
        "sub_line_spacing": style.line_spacing,
        "sub_margin_x": style.margin_x,
        "sub_margin_y": style.margin_y,
        "sub_align_x": style.align_x,
        "sub_align_y": style.align_y,
        "sub_pos": style.pos,
        "sub_scale": style.scale,
        "sub_ass_override": mode,
    }
    if style.font:
        values["sub_font"] = style.font
    else:
        values["sub_font"] = "sans-serif"
    return values


# свойства, которые имеют смысл для картиночных субтитров
IMAGE_PROPERTIES = ("sub_pos", "sub_scale")


# --- пресеты в файлах -----------------------------------------------------------------------

PRESET_FORMAT = "chopchop-subtitle-presets"
PRESET_VERSION = 1


def style_to_dict(style: SubtitleStyle) -> dict[str, object]:
    return {f.name: getattr(style, f.name) for f in fields(style)}


def style_from_dict(data: Mapping[str, object]) -> SubtitleStyle:
    """Стиль из словаря; неизвестные поля пропускаются, пропущенные берутся по умолчанию."""
    known = {f.name for f in fields(SubtitleStyle)}
    kept = {key: value for key, value in data.items() if key in known}
    return clamp(SubtitleStyle(**cast(Any, kept)))


def presets_to_json(presets: Mapping[str, SubtitleStyle]) -> str:
    payload = {
        "format": PRESET_FORMAT,
        "version": PRESET_VERSION,
        "presets": {name: style_to_dict(style) for name, style in presets.items()},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


class PresetFileError(ValueError):
    """Файл пресетов повреждён или не от этой программы."""


def presets_from_json(text: str) -> dict[str, SubtitleStyle]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise PresetFileError(f"не JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("format") != PRESET_FORMAT:
        raise PresetFileError("это не файл пресетов субтитров")
    raw = payload.get("presets")
    if not isinstance(raw, dict):
        raise PresetFileError("нет списка пресетов")
    result: dict[str, SubtitleStyle] = {}
    for name, data in raw.items():
        if isinstance(name, str) and name.strip() and isinstance(data, dict):
            result[name.strip()] = style_from_dict(data)
    if not result:
        raise PresetFileError("в файле нет ни одного пресета")
    return result
