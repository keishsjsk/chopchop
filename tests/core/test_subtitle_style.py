import json

import pytest

from chopchop.core import subtitle_style as ss
from chopchop.core.subtitle_style import (
    BUILTIN,
    PresetFileError,
    SubtitleStyle,
    clamp,
    is_image_codec,
    presets_from_json,
    presets_to_json,
    style_from_dict,
    style_to_dict,
    to_mpv,
)


def test_builtin_presets_are_valid_and_distinct() -> None:
    assert list(BUILTIN) == ["Стандарт", "Кино", "Высокий контраст", "Крупно"]
    for style in BUILTIN.values():
        assert clamp(style) == style  # встроенные значения в допустимых пределах
    assert len({repr(s) for s in BUILTIN.values()}) == 4
    assert BUILTIN["Стандарт"] == SubtitleStyle()


def test_clamp_pulls_values_into_range_and_fixes_junk() -> None:
    wild = SubtitleStyle(
        font_size=9999,
        outline_size=-5,
        color="red",
        back_opacity=500,
        margin_y=-3,
        align_x="diagonal",  # type: ignore[arg-type]
        scale=99,
        ass_mode="strange",  # type: ignore[arg-type]
    )
    fixed = clamp(wild)
    assert fixed.font_size == ss.SIZE_RANGE[1]
    assert fixed.outline_size == 0.0
    assert fixed.color == SubtitleStyle().color
    assert fixed.back_opacity == 100 and fixed.margin_y == 0
    assert fixed.align_x == "center" and fixed.scale == ss.SCALE_RANGE[1]
    assert fixed.ass_mode == "scale"


def test_to_mpv_maps_modes_alpha_and_border_style() -> None:
    plain = to_mpv(SubtitleStyle())
    assert plain["sub_ass_override"] == "scale"
    assert plain["sub_border_style"] == "outline-and-shadow"
    assert plain["sub_font"] == "sans-serif"
    assert plain["sub_color"] == "#FFFFFFFF"
    boxed = to_mpv(SubtitleStyle(back_enabled=True, back_opacity=50, back_color="#102030"))
    assert boxed["sub_border_style"] == "opaque-box"
    assert boxed["sub_back_color"] == "#80102030"  # 50 % -> 0x80
    for key, code in (("file", "no"), ("scale", "scale"), ("mine", "force")):
        assert to_mpv(SubtitleStyle(ass_mode=key))["sub_ass_override"] == code  # type: ignore[arg-type]
    named = to_mpv(SubtitleStyle(font="Arial", bold=True, italic=True, align_y="top"))
    assert named["sub_font"] == "Arial" and named["sub_bold"] is True
    assert named["sub_align_y"] == "top"


def test_codepages_include_the_common_ones() -> None:
    codes = [code for code, _ in ss.CODEPAGES]
    for needed in ("auto", "utf-8", "cp1251", "koi8-r", "cp1252"):
        assert needed in codes
    assert len(codes) == len(set(codes))


def test_image_codecs() -> None:
    assert is_image_codec("hdmv_pgs_subtitle") and is_image_codec("DVD_SUBTITLE")
    assert not is_image_codec("subrip") and not is_image_codec("ass") and not is_image_codec(None)


def test_json_round_trip_and_defaults_for_missing_fields() -> None:
    presets = {"Мой": SubtitleStyle(font="Arial", font_size=70, color="#FF0000")}
    again = presets_from_json(presets_to_json(presets))
    assert again == presets
    partial = style_from_dict({"font_size": 61, "unknown_field": 1})
    assert partial.font_size == 61 and partial.color == SubtitleStyle().color
    assert style_from_dict(style_to_dict(SubtitleStyle(italic=True))).italic


@pytest.mark.parametrize(
    "text",
    [
        "не json",
        "[]",
        json.dumps({"format": "other", "presets": {}}),
        json.dumps({"format": ss.PRESET_FORMAT, "presets": "x"}),
        json.dumps({"format": ss.PRESET_FORMAT, "presets": {}}),
    ],
)
def test_bad_preset_files_are_rejected(text: str) -> None:
    with pytest.raises(PresetFileError):
        presets_from_json(text)


def test_imported_values_are_clamped() -> None:
    payload = json.dumps(
        {"format": ss.PRESET_FORMAT, "version": 1, "presets": {"X": {"font_size": 5000}}}
    )
    assert presets_from_json(payload)["X"].font_size == ss.SIZE_RANGE[1]
