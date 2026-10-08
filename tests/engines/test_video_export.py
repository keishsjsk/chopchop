"""Экспорт настоящим ffmpeg: ролики генерируются на лету; без ffmpeg тесты пропускаются."""

import threading
from pathlib import Path

import pytest

from chopchop.core.video import AudioSettings, Clip, VideoProject
from chopchop.engines.ffmpeg import ExportCancelled, FfmpegError, FfmpegStep, run_steps
from chopchop.engines.probe import ProbeError, probe
from chopchop.engines.video_engine import build_plan
from media import FFMPEG, HAS_FFMPEG, make_video, make_wav, mean_volume, run

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")


def _clip(path: Path) -> Clip:
    return Clip(path, probe(path))


def _export(project: VideoProject, dest: Path, tmp_path: Path) -> list[float]:
    assert FFMPEG is not None
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    plan = build_plan(project, dest, FFMPEG, workdir)
    progress: list[float] = []
    run_steps(plan.steps, progress.append)
    return progress


def test_probe_reads_streams(tmp_path: Path) -> None:
    info = probe(make_video(tmp_path / "a.mp4", seconds=4, size=(320, 240), fps=25))
    assert (info.width, info.height) == (320, 240)
    assert info.duration == pytest.approx(4.0, abs=0.2)
    assert info.fps == pytest.approx(25.0)
    assert info.video_codec == "h264"
    assert info.audio is not None
    assert (info.audio.codec, info.audio.sample_rate, info.audio.channels) == ("aac", 44100, 2)


def test_probe_video_without_audio(tmp_path: Path) -> None:
    info = probe(make_video(tmp_path / "silent.mp4", audio=False))
    assert not info.has_audio


def test_probe_rejects_non_video(tmp_path: Path) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video")
    with pytest.raises(ProbeError):
        probe(junk)
    with pytest.raises(ProbeError):
        probe(make_wav(tmp_path / "sound.wav"))  # нет видеодорожки


def test_fast_trim_without_reencoding(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=8)
    project = VideoProject((_clip(source).with_trim(2, 5),))
    progress = _export(project, tmp_path / "out.mp4", tmp_path)
    result = probe(tmp_path / "out.mp4")
    assert result.duration == pytest.approx(3.0, abs=0.3)
    assert result.video_codec == "h264"
    assert result.has_audio
    assert progress[-1] == pytest.approx(1.0)
    assert all(a <= b for a, b in zip(progress, progress[1:], strict=False))


def test_export_strips_metadata(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=3, title="Secret title")
    _export(VideoProject((_clip(source),)), tmp_path / "out.mp4", tmp_path)
    tags = run(
        [str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-show_format"]
        + ["-print_format", "json", str(tmp_path / "out.mp4")]
    ).stdout
    assert "Secret title" not in tags


def test_mute_removes_audio(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=3)
    project = VideoProject((_clip(source),), AudioSettings(mute=True))
    _export(project, tmp_path / "out.mp4", tmp_path)
    assert not probe(tmp_path / "out.mp4").has_audio


def test_volume_changes_loudness(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=3)
    project = VideoProject((_clip(source),), AudioSettings(volume=0.5))
    _export(project, tmp_path / "quiet.mp4", tmp_path)
    assert mean_volume(source) - mean_volume(tmp_path / "quiet.mp4") == pytest.approx(6.0, abs=1.0)
    assert probe(tmp_path / "quiet.mp4").video_codec == "h264"


def test_replacement_audio_keeps_video_length(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=5, audio=False)
    song = make_wav(tmp_path / "song.wav", seconds=2)  # короче видео
    project = VideoProject((_clip(source),), AudioSettings(replacement=song))
    _export(project, tmp_path / "out.mp4", tmp_path)
    result = probe(tmp_path / "out.mp4")
    assert result.has_audio
    assert result.duration == pytest.approx(5.0, abs=0.3)


def test_concat_joins_trimmed_clips(tmp_path: Path) -> None:
    first = make_video(tmp_path / "a.mp4", seconds=6)
    second = make_video(tmp_path / "b.mp4", seconds=4)
    project = VideoProject((_clip(first).with_trim(1, 4), _clip(second)))
    _export(project, tmp_path / "joined.mp4", tmp_path)
    result = probe(tmp_path / "joined.mp4")
    assert result.duration == pytest.approx(7.0, abs=0.5)
    assert result.has_audio


def test_mkv_container_works(tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=3)
    _export(VideoProject((_clip(source).with_trim(0, 2),)), tmp_path / "out.mkv", tmp_path)
    assert probe(tmp_path / "out.mkv").duration == pytest.approx(2.0, abs=0.3)


def test_ffmpeg_error_message_is_reported(tmp_path: Path) -> None:
    assert FFMPEG is not None
    step = FfmpegStep(
        (str(FFMPEG), "-nostdin", "-loglevel", "error", "-i", str(tmp_path / "missing.mp4"))
        + (str(tmp_path / "o.mp4"),),
        1.0,
        tmp_path / "o.mp4",
    )
    with pytest.raises(FfmpegError, match="missing.mp4"):
        run_steps([step], lambda _fraction: None)


def test_cancel_stops_export(tmp_path: Path) -> None:
    assert FFMPEG is not None
    source = make_video(tmp_path / "a.mp4", seconds=4)
    plan = build_plan(VideoProject((_clip(source),)), tmp_path / "out.mp4", FFMPEG, tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        run_steps(plan.steps, lambda _fraction: None, cancel)
