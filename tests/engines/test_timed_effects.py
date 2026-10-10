"""Время показа в графе фильтров: enable='between(t,a,b)' у текста и областей скрытия."""

from pathlib import Path

from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text
from chopchop.core.video import VideoEffects
from chopchop.engines.video_filters import build_effects_graph, result_enable

SIZE = (640, 360)


def _graph(effects: VideoEffects, **kwargs) -> str:  # type: ignore[no-untyped-def]
    files = {i: Path(f"/w/text{i:02d}.txt") for i in range(len(effects.texts))}
    return build_effects_graph(effects, SIZE, files, None, **kwargs)


def test_default_window_adds_no_enable() -> None:
    effects = VideoEffects(texts=(Text("a", 1, 2),), redacts=(Redact(Rect(0, 0, 50, 50)),))
    assert "enable" not in _graph(effects)
    assert result_enable(0.0, -1.0) is None


def test_text_with_a_window_uses_between() -> None:
    graph = _graph(VideoEffects(texts=(Text("a", 1, 2, show_from=2.0, show_to=4.5),)))
    assert "drawtext=" in graph and ":enable='between(t,2.000,4.500)'" in graph


def test_open_end_uses_gte_and_open_start_between() -> None:
    assert "enable='gte(t,3.000)'" in _graph(VideoEffects(texts=(Text("a", 0, 0, show_from=3.0),)))
    assert "enable='between(t,0.000,1.500)'" in _graph(
        VideoEffects(texts=(Text("a", 0, 0, show_to=1.5),))
    )


def test_fill_redact_has_enable_on_drawbox() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(10, 10, 100, 50), show_from=1.0, show_to=2.0),))
    graph = _graph(effects)
    expected = "drawbox=x=10:y=10:w=100:h=50:color=0x000000:t=fill"
    assert expected + ":enable='between(t,1.000,2.000)'" in graph


def test_blur_and_pixelate_redacts_put_enable_on_the_overlay() -> None:
    for mode in ("blur", "pixelate"):
        effects = VideoEffects(
            redacts=(Redact(Rect(10, 10, 100, 50), mode=mode, show_from=1.0, show_to=2.0),)
        )
        graph = _graph(effects)
        assert "overlay=10:10:enable='between(t,1.000,2.000)'" in graph, mode


def test_custom_enable_for_replaces_the_time_base() -> None:
    effects = VideoEffects(texts=(Text("a", 0, 0, show_from=5.0, show_to=9.0),))
    graph = _graph(effects, enable_for=lambda a, b: f"between(t,{a + 10:.3f},{b + 10:.3f})")
    assert "enable='between(t,15.000,19.000)'" in graph  # превью по времени файла
    hidden = _graph(effects, enable_for=lambda a, b: "0")
    assert "enable='0'" in hidden
