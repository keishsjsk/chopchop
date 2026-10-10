"""Вырезы из середины настоящим ffmpeg: длительность, синхронизация, привязка к ключевым кадрам."""

import json
from pathlib import Path

import pytest

from chopchop.core.keyframes import junctions, snap_back
from chopchop.core.video import Clip, VideoProject
from chopchop.engines.ffmpeg import run_steps
from chopchop.engines.keyframes import read_keyframes
from chopchop.engines.probe import probe
from chopchop.engines.video_engine import build_plan
from media import FFMPEG, FFPROBE, HAS_FFMPEG, make_video, run

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")

SECONDS = 10  # в ролике ключевой кадр каждую секунду (см. media.make_video)


def _clip(path: Path) -> Clip:
    return Clip(path, probe(path))


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
    project = VideoProject((_clip(source).remove_span(3.0, 6.0),))
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
    clip = _clip(source).remove_span(3.0, 6.5)  # второй кусок начинается на 6.5, не на ключевом
    project = VideoProject((clip,))
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
    project = VideoProject((_clip(source).remove_span(3.0, 6.5),))
    result = _export(project, tmp_path, precise=True)
    video, audio = _durations(result)
    expected = 3.0 + (SECONDS - 6.5)
    assert video == pytest.approx(expected, abs=0.1)
    assert abs(video - audio) < 0.15
    assert probe(result).duration == pytest.approx(expected, abs=0.1)


def test_precise_cut_with_edge_trim_and_two_holes(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=SECONDS)
    clip = _clip(source).with_trim(1.0, 9.0).remove_span(2.5, 3.5).remove_span(6.0, 7.5)
    result = _export(VideoProject((clip,)), tmp_path, precise=True)
    video, audio = _durations(result)
    assert video == pytest.approx(8.0 - 1.0 - 1.5, abs=0.12)
    assert abs(video - audio) < 0.15


def test_fast_join_of_a_cut_clip_and_a_second_file_in_another_container(tmp_path: Path) -> None:
    assert FFMPEG is not None
    first = make_video(tmp_path / "a.mp4", seconds=6)
    second_mp4 = make_video(tmp_path / "b_src.mp4", seconds=4)
    second = tmp_path / "b.mkv"  # другой контейнер с теми же кодеками
    run([str(FFMPEG), "-v", "error", "-y", "-i", str(second_mp4), "-c", "copy", str(second)])
    project = VideoProject((_clip(first).remove_span(2.0, 4.0), _clip(second)))
    result = _export(project, tmp_path)
    video, audio = _durations(result)
    assert video == pytest.approx(4.0 + 4.0, abs=0.4)
    assert abs(video - audio) < 0.3  # раньше смесь контейнеров растягивала звук в разы
