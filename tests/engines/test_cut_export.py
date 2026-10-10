"""Вырезы из середины настоящим ffmpeg: длительность, синхронизация, привязка к ключевым кадрам."""

import json
from pathlib import Path

import pytest

from chopchop.core.keyframes import junctions, snap_back
from chopchop.core.video import Clip, VideoProject, legacy_blocks
from chopchop.engines.ffmpeg import run_steps
from chopchop.engines.keyframes import read_keyframes
from chopchop.engines.probe import probe
from chopchop.engines.video_engine import build_plan
from media import FFMPEG, FFPROBE, HAS_FFMPEG, make_video, run

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")

SECONDS = 10  # в ролике ключевой кадр каждую секунду (см. media.make_video)


def _clip(path: Path) -> Clip:
    return Clip(path, probe(path))


def _blocks(path: Path, *cuts: tuple[float, float], start: float = 0.0) -> tuple[Clip, ...]:
    """Блоки файла без вырезанных кусков (вырезы во времени файла)."""
    return legacy_blocks(path, probe(path), start=start, end=-1.0, cuts=tuple(cuts))


def _export(project: VideoProject, tmp_path: Path, *, precise: bool = False) -> Path:
    assert FFMPEG is not None
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    dest = tmp_path / ("precise.mp4" if precise else "fast.mp4")
    keyframes = {c.path: read_keyframes(c.path, FFPROBE) for c in project.clips}
    plan = build_plan(project, dest, FFMPEG, work, precise=precise, keyframes=keyframes)
    run_steps(plan.steps, lambda _fraction: None)
    return dest


def _durations(path: Path) -> tuple[float, float]:
    assert FFPROBE is not None
    out = run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,duration"]
        + ["-of", "json", str(path)]
    ).stdout
    streams = {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}
    return streams["video"], streams["audio"]


def test_keyframes_are_found_once_a_second(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    frames = read_keyframes(source, FFPROBE)
    assert len(frames) == SECONDS and frames[0] == 0.0
    assert all(
        b - a == pytest.approx(1.0, abs=0.05) for a, b in zip(frames, frames[1:], strict=False)
    )
    assert snap_back(frames, 4.6) == pytest.approx(4.0, abs=0.05)


def test_fast_cut_on_keyframes_removes_the_middle_without_desync(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    project = VideoProject(_blocks(source, (3.0, 6.0)))
    result = _export(project, tmp_path)
    video, audio = _durations(result)
    assert video == pytest.approx(7.0, abs=0.3)
    assert abs(video - audio) < 0.25  # звук не уехал от видео на стыке
    assert probe(result).duration == pytest.approx(7.0, abs=0.3)
    assert probe(result).video_codec == "h264"  # без перекодирования


def test_fast_cut_snaps_start_to_the_previous_keyframe_and_flags_the_junction(
    tmp_path: Path,
) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    project = VideoProject(_blocks(source, (3.0, 6.5)))  # второй блок с 6.5, не с ключевого
    frames = read_keyframes(source, FFPROBE)
    found = junctions(project, {source: frames})
    assert [j.precise for j in found] == [False, True]  # на втором стыке нужна точная резка
    assert found[1].snapped == pytest.approx(6.0, abs=0.05)
    result = _export(project, tmp_path)
    video, audio = _durations(result)
    # копирование начинает с ключевого кадра 6.0, поэтому результат на полсекунды длиннее
    assert video == pytest.approx(3.0 + (SECONDS - 6.0), abs=0.35)
    assert abs(video - audio) < 0.3


def test_precise_cut_is_accurate_to_the_frame(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    project = VideoProject(_blocks(source, (3.0, 6.5)))
    result = _export(project, tmp_path, precise=True)
    video, audio = _durations(result)
    expected = 3.0 + (SECONDS - 6.5)
    assert video == pytest.approx(expected, abs=0.1)
    assert abs(video - audio) < 0.15
    assert probe(result).duration == pytest.approx(expected, abs=0.1)


def test_precise_cut_with_edge_trim_and_two_holes(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    blocks = legacy_blocks(source, probe(source), start=1.0, end=9.0, cuts=((2.5, 3.5), (6.0, 7.5)))
    result = _export(VideoProject(blocks), tmp_path, precise=True)
    video, audio = _durations(result)
    assert video == pytest.approx(8.0 - 1.0 - 1.5, abs=0.2)  # три блока: по кадру на стыке
    assert abs(video - audio) < 0.15


def test_fast_join_of_a_cut_clip_and_a_second_file_in_another_container(tmp_path: Path) -> None:
    assert FFMPEG is not None
    first = make_video(tmp_path / "a.mp4", seconds=6)
    second_mp4 = make_video(tmp_path / "b_src.mp4", seconds=4)
    second = tmp_path / "b.mkv"  # другой контейнер с теми же кодеками
    run([str(FFMPEG), "-v", "error", "-y", "-i", str(second_mp4), "-c", "copy", str(second)])
    project = VideoProject((*_blocks(first, (2.0, 4.0)), _clip(second)))
    result = _export(project, tmp_path)
    video, audio = _durations(result)
    assert video == pytest.approx(4.0 + 4.0, abs=0.4)
    assert abs(video - audio) < 0.3  # раньше смесь контейнеров растягивала звук в разы


def _pixel(path: Path, at: float, x: int, y: int) -> tuple[int, int, int]:
    assert FFMPEG is not None
    out = run(
        [str(FFMPEG), "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1"]
        + ["-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        binary=True,
    ).stdout
    return out[0], out[1], out[2]


def test_timed_redact_shows_only_in_its_window_after_a_cut(tmp_path: Path) -> None:
    from chopchop.core.geometry import Rect
    from chopchop.core.operations import Redact
    from chopchop.core.video import RemoveRange, VideoEffects

    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    clip = _clip(source)
    redact = Redact(Rect(100, 80, 100, 80), show_from=4.0, show_to=6.0)  # время итога
    project = VideoProject((clip,), effects=VideoEffects(redacts=(redact,)))
    project = RemoveRange(1.0, 3.0).apply(project)  # окно уехало бы на 2 секунды раньше
    from chopchop.core.timing import retime

    old = VideoProject((clip,), effects=VideoEffects(redacts=(redact,)))
    project, _notes = retime(old, project)
    assert (project.effects.redacts[0].show_from, project.effects.redacts[0].show_to) == (2.0, 4.0)
    result = _export(project, tmp_path, precise=True)
    inside = _pixel(result, 3.0, 150, 120)
    before = _pixel(result, 1.0, 150, 120)
    after = _pixel(result, 5.0, 150, 120)
    assert sum(inside) < 30  # чёрная заливка видна внутри окна
    assert sum(before) > 60 and sum(after) > 60  # вне окна — картинка


# --- перестановка блоков: содержимое и порядок -----------------------------------------------


def _frame(path: Path, at: float):  # type: ignore[no-untyped-def]
    """Кадр файла на секунде `at` как картинка Pillow."""
    import io

    from PIL import Image

    assert FFMPEG is not None
    png = run(
        [str(FFMPEG), "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1"]
        + ["-f", "image2pipe", "-vcodec", "png", "-"],
        binary=True,
    ).stdout
    return Image.open(io.BytesIO(png)).convert("L")


def _distance(a, b) -> float:  # type: ignore[no-untyped-def]
    from PIL import ImageChops, ImageStat

    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])


def _source_second_at(result: Path, at: float, source: Path, candidates: list[float]) -> float:
    """На какой секунде исходника лежит кадр результата: ближайший по картинке из кандидатов."""
    shot = _frame(result, at)
    return min(candidates, key=lambda c: _distance(shot, _frame(source, c)))


@pytest.mark.parametrize("precise", [False, True])
def test_moving_the_middle_block_to_the_end_keeps_length_and_order(
    tmp_path: Path, precise: bool
) -> None:
    from chopchop.core.video import MoveBlock

    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    project = VideoProject((_clip(source),)).split_at(3.0).split_at(6.0)
    project = MoveBlock(1, 2).apply(project)  # 0-3, 6-10, 3-6
    result = _export(project, tmp_path, precise=precise)
    video, audio = _durations(result)
    assert video == pytest.approx(SECONDS, abs=0.3)
    assert abs(video - audio) < 0.3
    seconds = [float(s) + 0.5 for s in range(SECONDS)]
    # по картинке: 1,5 с результата — 1,5 с исходника; 4,5 — 7,5; 8,5 — 4,5
    assert _source_second_at(result, 1.5, source, seconds) == pytest.approx(1.5, abs=0.6)
    assert _source_second_at(result, 4.5, source, seconds) == pytest.approx(7.5, abs=0.6)
    assert _source_second_at(result, 8.5, source, seconds) == pytest.approx(4.5, abs=0.6)


@pytest.mark.parametrize("precise", [False, True])
def test_cut_the_middle_and_move_the_tail_first(tmp_path: Path, precise: bool) -> None:
    from chopchop.core.video import MoveBlock, RemoveBlock

    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    project = VideoProject((_clip(source),)).split_at(3.0).split_at(6.0)
    project = RemoveBlock(1).apply(project)  # остаются 0-3 и 6-10
    project = MoveBlock(1, 0).apply(project)  # хвост в начало: 6-10, 0-3
    result = _export(project, tmp_path, precise=precise)
    video, audio = _durations(result)
    assert video == pytest.approx(7.0, abs=0.3)
    assert abs(video - audio) < 0.3
    seconds = [float(s) + 0.5 for s in range(SECONDS)]
    assert _source_second_at(result, 1.5, source, seconds) == pytest.approx(7.5, abs=0.6)
    assert _source_second_at(result, 5.5, source, seconds) == pytest.approx(1.5, abs=0.6)
