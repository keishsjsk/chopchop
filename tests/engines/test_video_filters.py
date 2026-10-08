import re
from pathlib import Path

import pytest

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, Redact, Text
from chopchop.core.video import VideoEffects
from chopchop.engines.video_filters import (
    adjust_filter,
    build_effects_graph,
    hex_color,
    output_frame_size,
    quote_path,
)

SIZE = (640, 360)


def _graph(effects: VideoEffects, **kwargs: object) -> str:
    return build_effects_graph(effects, SIZE, {}, **kwargs)  # type: ignore[arg-type]


def test_empty_effects_are_a_passthrough_with_pixel_format() -> None:
    assert _graph(VideoEffects()) == "[in]format=yuv420p[out]"
    assert _graph(VideoEffects(), geometry=False) == "[in]null[out]"


def test_fill_redact_uses_drawbox() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(10, 20, 100, 50), "fill", color=(255, 0, 0)),))
    graph = _graph(effects, geometry=False)
    assert graph == "[in]drawbox=x=10:y=20:w=100:h=50:color=0xFF0000:t=fill[out]"


def test_blur_redact_blurs_only_a_copy_of_the_region() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(10, 20, 100, 60), "blur", strength=30.0),))
    parts = _graph(effects, geometry=False).split(";")
    assert parts[0] == "[in]split[a1][b1]"
    assert parts[1] == "[b1]crop=100:60:10:20,boxblur=15:2[r1]"  # радиус не больше четверти стороны
    assert parts[2] == "[a1][r1]overlay=10:20[out]"


def test_pixelate_downscales_then_upscales_without_smoothing() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(0, 0, 100, 60), "pixelate", strength=10.0),))
    graph = _graph(effects, geometry=False)
    assert "crop=100:60:0:0,scale=10:6,scale=100:60:flags=neighbor[r1]" in graph


def test_redact_outside_frame_is_ignored() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(900, 900, 50, 50), "fill"),))
    assert _graph(effects, geometry=False) == "[in]null[out]"


def test_several_effects_chain_in_fixed_order() -> None:
    effects = VideoEffects(
        redacts=(Redact(Rect(0, 0, 50, 50), "fill"), Redact(Rect(100, 100, 80, 80), "blur", 20.0)),
        adjust=Adjust(contrast=1.2),
        filter="grayscale",
    )
    graph = _graph(effects, geometry=False)
    first_drawbox = graph.index("drawbox")
    assert first_drawbox < graph.index("boxblur") < graph.index("eq=") < graph.index("hue=s=0")
    labels = [re.search(r"\[(\w+)\]$", part).group(1) for part in graph.split(";")]  # type: ignore[union-attr]
    assert labels[-1] == "out"
    assert len(set(labels)) == len(labels)  # метки не повторяются


def test_text_uses_textfile_font_and_quoting(tmp_path: Path) -> None:
    effects = VideoEffects(texts=(Text("Привет: мир", 40.4, 60.6, 36.0, (255, 255, 0)),))
    textfile = tmp_path / "text00.txt"
    font = Path("C:/Windows/Fonts/arial.ttf")
    graph = build_effects_graph(
        effects, SIZE, {0: textfile}, font, geometry=False, in_label="vid1", out_label="vo"
    )
    assert graph.startswith("[vid1]drawtext=textfile='")
    assert graph.endswith("[vo]")
    assert "x=40:y=61:fontsize=36:fontcolor=0xFFFF00" in graph
    assert "fontfile='C\\:/Windows/Fonts/arial.ttf'" in graph
    assert "Привет" not in graph  # сам текст в граф не попадает, только путь к файлу


def test_blank_or_unwritten_text_is_skipped() -> None:
    effects = VideoEffects(texts=(Text("   ", 0, 0), Text("x", 0, 0)))
    assert _graph(effects, geometry=False) == "[in]null[out]"  # у второго нет файла


def test_adjust_mapping() -> None:
    text = adjust_filter(Adjust(brightness=1.5, contrast=1.2, saturation=0.0, gamma=2.0))
    assert text == "eq=brightness=0.200:contrast=1.200:saturation=0.000:gamma=2.000"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("grayscale", "hue=s=0"), ("blur", "gblur=sigma=3"), ("sharpen", "unsharp=")],
)
def test_filters(name: str, expected: str) -> None:
    graph = _graph(VideoEffects(filter=name), geometry=False)  # type: ignore[arg-type]
    assert expected in graph


def test_crop_is_even_and_applied_after_picture_effects() -> None:
    effects = VideoEffects(crop=Rect(11, 21, 201, 101), filter="sepia")
    graph = _graph(effects)
    assert graph.index("colorchannelmixer") < graph.index("crop=")
    assert "crop=200:100:11:21" in graph  # размеры округляются вниз до чётных (нужно для h264)
    assert graph.endswith("format=yuv420p[out]")


def test_geometry_false_skips_crop_and_rotation() -> None:
    effects = VideoEffects(crop=Rect(0, 0, 100, 100), rotation=90, flip_h=True)
    assert _graph(effects, geometry=False) == "[in]null[out]"


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [(90, "transpose=1"), (270, "transpose=2"), (180, "hflip,vflip")],
)
def test_rotation(rotation: int, expected: str) -> None:
    assert f"{expected},format=yuv420p" in _graph(VideoEffects(rotation=rotation))


def test_flips() -> None:
    graph = _graph(VideoEffects(flip_h=True, flip_v=True))
    assert "hflip,vflip,format=yuv420p" in graph


def test_output_frame_size() -> None:
    assert output_frame_size(VideoEffects(), SIZE) == SIZE
    assert output_frame_size(VideoEffects(crop=Rect(0, 0, 301, 101)), SIZE) == (300, 100)
    assert output_frame_size(VideoEffects(crop=Rect(0, 0, 300, 100), rotation=90), SIZE) == (
        100,
        300,
    )
    assert output_frame_size(VideoEffects(rotation=270), SIZE) == (360, 640)


def test_quote_path_and_color() -> None:
    assert quote_path(Path("C:/a b/it's.txt")) == "'C\\:/a b/it'\\''s.txt'"
    assert hex_color((1, 2, 255)) == "0x0102FF"
