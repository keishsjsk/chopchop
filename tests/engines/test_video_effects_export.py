"""Экспорт с перекодированием настоящим ffmpeg: результат проверяется по пикселям и параметрам."""

import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from media import FFMPEG, HAS_FFMPEG, make_video
from quickedit.core.geometry import Rect
from quickedit.core.operations import Adjust, Redact, Text
from quickedit.core.video import AudioSettings, Clip, VideoEffects, VideoProject
from quickedit.engines.ffmpeg import run_steps
from quickedit.engines.fonts import find_font_path
from quickedit.engines.probe import probe
from quickedit.engines.video_engine import build_plan

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")


def _clip(path: Path) -> Clip:
    return Clip(path, probe(path))


def _export(project: VideoProject, tmp_path: Path, name: str = "out.mp4", **kwargs: object) -> Path:
    assert FFMPEG is not None
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    dest = tmp_path / name
    plan = build_plan(project, dest, FFMPEG, workdir, **kwargs)  # type: ignore[arg-type]
    progress: list[float] = []
    run_steps(plan.steps, progress.append)
    assert progress[-1] == pytest.approx(1.0)
    return dest


def _frame(path: Path, at: float = 1.0) -> Image.Image:
    """Кадр ролика в секунде `at` (PNG через ffmpeg)."""
    assert FFMPEG is not None
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-ss", str(at), "-i", str(path)]
        + ["-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def _mean_diff(a: Image.Image, b: Image.Image, box: tuple[int, int, int, int]) -> float:
    diff = ImageChops.difference(a.crop(box), b.crop(box))
    return sum(ImageStat.Stat(diff).mean) / 3


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_video(tmp_path / "src.mp4", seconds=4, size=(320, 240))


def test_crop_changes_frame_size(tmp_path: Path, source: Path) -> None:
    effects = VideoEffects(crop=Rect(40, 20, 160, 120))
    out = _export(VideoProject((_clip(source),), effects=effects), tmp_path)
    info = probe(out)
    assert (info.width, info.height) == (160, 120)
    assert info.video_codec == "h264"
    assert info.has_audio
    assert info.duration == pytest.approx(4.0, abs=0.3)


def test_rotation_swaps_dimensions(tmp_path: Path, source: Path) -> None:
    out = _export(VideoProject((_clip(source),), effects=VideoEffects(rotation=90)), tmp_path)
    info = probe(out)
    assert (info.width, info.height) == (240, 320)


def test_horizontal_flip_mirrors_the_picture(tmp_path: Path, source: Path) -> None:
    plain = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(filter="blur", rotation=0)),
            tmp_path,
            "a.mp4",
        )
    )
    flipped = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(filter="blur", flip_h=True)),
            tmp_path,
            "b.mp4",
        )
    )
    mirrored = plain.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    assert _mean_diff(flipped, mirrored, (0, 0, 320, 240)) < 6


def test_fill_redact_covers_only_its_region(tmp_path: Path, source: Path) -> None:
    base = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(gamma=1.0001))),
            tmp_path,
            "base.mp4",
        )
    )
    effects = VideoEffects(redacts=(Redact(Rect(100, 100, 80, 60), "fill", color=(255, 0, 255)),))
    out = _frame(_export(VideoProject((_clip(source),), effects=effects), tmp_path, "red.mp4"))
    r, g, b = out.getpixel((140, 130))
    assert r > 200 and b > 200 and g < 70  # пурпурная заливка
    assert _mean_diff(out, base, (0, 0, 90, 90)) < 6  # вне области картинка прежняя


@pytest.mark.parametrize("mode", ["blur", "pixelate"])
def test_blur_and_pixelate_change_only_the_region(tmp_path: Path, source: Path, mode: str) -> None:
    base = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(gamma=1.0001))),
            tmp_path,
            "base.mp4",
        )
    )
    effects = VideoEffects(redacts=(Redact(Rect(100, 60, 120, 120), mode, strength=16.0),))  # type: ignore[arg-type]
    out = _frame(_export(VideoProject((_clip(source),), effects=effects), tmp_path, "x.mp4"))
    assert _mean_diff(out, base, (100, 60, 220, 180)) > 8
    assert _mean_diff(out, base, (0, 0, 90, 50)) < 6


def test_text_is_drawn_with_cyrillic(tmp_path: Path, source: Path) -> None:
    font = find_font_path()
    base = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(gamma=1.0001))),
            tmp_path,
            "base.mp4",
        )
    )
    effects = VideoEffects(texts=(Text("Привет, мир", 20, 150, 40.0, (255, 255, 0)),))
    out = _frame(
        _export(VideoProject((_clip(source),), effects=effects), tmp_path, "t.mp4", font=font)
    )
    assert _mean_diff(out, base, (15, 145, 310, 200)) > 4
    assert _mean_diff(out, base, (0, 0, 320, 100)) < 6


def test_color_and_filters(tmp_path: Path, source: Path) -> None:
    gray = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(filter="grayscale")),
            tmp_path,
            "g.mp4",
        )
    )
    desaturated = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(saturation=0.0))),
            tmp_path,
            "d.mp4",
        )
    )
    for image in (gray, desaturated):
        for point in ((40, 40), (160, 120), (280, 200)):
            r, g, b = image.getpixel(point)
            assert max(r, g, b) - min(r, g, b) < 14  # цвет убран
    sepia = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(filter="sepia")), tmp_path, "s.mp4"
        )
    )
    r, g, b = (sum(ImageStat.Stat(sepia).mean[i] for i in (c,)) for c in range(3))
    assert r > g > b  # тёплый оттенок


def test_brightness_makes_picture_lighter(tmp_path: Path, source: Path) -> None:
    dark = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(brightness=0.5))),
            tmp_path,
            "dark.mp4",
        )
    )
    light = _frame(
        _export(
            VideoProject((_clip(source),), effects=VideoEffects(adjust=Adjust(brightness=1.6))),
            tmp_path,
            "light.mp4",
        )
    )
    assert sum(ImageStat.Stat(light).mean) > sum(ImageStat.Stat(dark).mean) + 30


def test_precise_trim_is_frame_accurate(tmp_path: Path, source: Path) -> None:
    project = VideoProject((_clip(source).with_trim(1.5, 3.3),))
    precise = _export(project, tmp_path, "precise.mp4", precise=True)
    assert probe(precise).duration == pytest.approx(1.8, abs=0.1)
    assert probe(precise).has_audio


def test_join_of_clips_with_different_parameters(tmp_path: Path, source: Path) -> None:
    other = make_video(tmp_path / "other.mp4", seconds=3, size=(480, 270), fps=30)
    silent = make_video(tmp_path / "silent.mp4", seconds=2, size=(320, 240), audio=False)
    project = VideoProject((_clip(source), _clip(other), _clip(silent)))
    assert project.reencode_reason() == "clips"
    out = _export(project, tmp_path, "joined.mp4")
    info = probe(out)
    assert (info.width, info.height) == (320, 240)  # размер первого клипа
    assert info.fps == pytest.approx(25.0, abs=0.5)
    assert info.duration == pytest.approx(9.0, abs=0.5)
    assert info.has_audio  # у беззвучного клипа вставлена тишина, звук не «уехал»
    assert info.audio is not None
    assert info.audio.sample_rate == 48000


def test_join_with_trim_effects_volume_and_mute(tmp_path: Path, source: Path) -> None:
    other = make_video(tmp_path / "other.mp4", seconds=3, size=(480, 270), fps=30)
    project = VideoProject(
        (_clip(source).with_trim(1, 3), _clip(other).with_trim(0, 2)),
        AudioSettings(mute=True),
        VideoEffects(filter="sepia", crop=Rect(0, 0, 160, 120)),
    )
    out = _export(project, tmp_path, "mix.mkv")
    info = probe(out)
    assert (info.width, info.height) == (160, 120)
    assert info.duration == pytest.approx(4.0, abs=0.4)
    assert not info.has_audio


def test_replacement_audio_with_effects(tmp_path: Path, source: Path) -> None:
    from media import make_wav

    song = make_wav(tmp_path / "song.wav", seconds=2)
    project = VideoProject(
        (_clip(source),), AudioSettings(replacement=song), VideoEffects(filter="blur")
    )
    info = probe(_export(project, tmp_path))
    assert info.has_audio
    assert info.duration == pytest.approx(4.0, abs=0.3)  # звук короче видео, ролик не обрывается
