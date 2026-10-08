"""Планировщик с перекодированием: сравнение аргументов ffmpeg, без запуска."""

from pathlib import Path

import pytest

from quickedit.core.document import AudioInfo, MediaInfo
from quickedit.core.geometry import Rect
from quickedit.core.operations import Adjust, Redact, Text
from quickedit.core.video import AudioSettings, Clip, VideoEffects, VideoProject
from quickedit.engines.video_engine import ExportPlan, build_plan

FFMPEG = Path("/opt/ffmpeg")
AUDIO = AudioInfo("aac", 44100, 2)
INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AUDIO)
SMALL = MediaInfo(640, 360, 30.0, 30.0, "h264", "yuv420p", 0, AUDIO)
SILENT = MediaInfo(1280, 720, 20.0, 25.0, "h264", "yuv420p", 0, None)


def _clip(name: str, info: MediaInfo = INFO) -> Clip:
    return Clip(Path(name), info)


def _plan(project: VideoProject, tmp_path: Path, **kwargs: object) -> ExportPlan:
    return build_plan(project, tmp_path / "out.mp4", FFMPEG, tmp_path, **kwargs)  # type: ignore[arg-type]


def _args(plan: ExportPlan) -> list[str]:
    assert len(plan.steps) == 1
    return list(plan.steps[0].args)


def _after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _graph(plan: ExportPlan) -> str:
    return _after(_args(plan), "-filter_complex")


def test_effects_force_reencoding_of_video(tmp_path: Path) -> None:
    effects = VideoEffects(adjust=Adjust(contrast=1.2))
    plan = _plan(VideoProject((_clip("a.mp4"),), effects=effects), tmp_path)
    args = _args(plan)
    assert plan.reencodes_video
    assert _after(args, "-c:v") == "libx264"
    assert _after(args, "-map") == "[vout]"
    assert "[0:v]eq=" in _graph(plan)
    assert args[args.index("-map", args.index("-map") + 1) + 1] == "0:a?"  # звук как есть, в AAC
    assert _after(args, "-c:a") == "aac"
    assert plan.reencodes_audio


def test_precise_trim_reencodes_only_when_something_is_trimmed(tmp_path: Path) -> None:
    trimmed = VideoProject((_clip("a.mp4").with_trim(10, 20),))
    fast = _plan(trimmed, tmp_path)
    assert not fast.reencodes_video
    assert "-c" in _args(fast)  # копирование
    precise = _plan(trimmed, tmp_path, precise=True)
    args = _args(precise)
    assert precise.reencodes_video
    assert args.index("-ss") < args.index("-i")  # точная обрезка тоже идёт с -ss до -i
    assert _after(args, "-ss") == "10.000"
    assert _after(args, "-to") == "20.000"
    untouched = _plan(VideoProject((_clip("a.mp4"),)), tmp_path, precise=True)
    assert not untouched.reencodes_video  # резать нечего — копируем


def test_different_clips_are_joined_with_reencoding(tmp_path: Path) -> None:
    project = VideoProject((_clip("a.mp4"), _clip("b.mp4", SMALL)))
    plan = _plan(project, tmp_path)
    graph = _graph(plan)
    assert plan.reencodes_video
    assert "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:" in graph
    assert "[1:v]scale=1280:720" in graph  # второй клип приводится к размеру первого
    assert "fps=25.000" in graph
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][acat]" in graph
    assert "[vcat]" in graph
    assert list(plan.steps[0].args).count("-i") == 2


def test_clip_without_audio_gets_silence_in_a_mixed_join(tmp_path: Path) -> None:
    project = VideoProject((_clip("a.mp4"), _clip("b.mp4", SILENT)))
    graph = _graph(_plan(project, tmp_path))
    assert "anullsrc=r=48000:cl=stereo,atrim=duration=20.000,asetpts=PTS-STARTPTS[a1]" in graph
    assert "concat=n=2:v=1:a=1" in graph


def test_join_of_silent_clips_has_no_audio(tmp_path: Path) -> None:
    project = VideoProject(
        (_clip("a.mp4", SILENT), _clip("b.mp4", SILENT)), effects=VideoEffects(filter="blur")
    )
    plan = _plan(project, tmp_path)
    assert "concat=n=2:v=1:a=0[vcat]" in _graph(plan)
    assert "-an" in _args(plan)
    assert not plan.reencodes_audio


def test_volume_applies_after_join(tmp_path: Path) -> None:
    project = VideoProject((_clip("a.mp4"), _clip("b.mp4", SMALL)), AudioSettings(volume=0.5))
    plan = _plan(project, tmp_path)
    assert "[acat]volume=0.500[aout]" in _graph(plan)
    assert "[aout]" in _args(plan)


def test_mute_and_replacement(tmp_path: Path) -> None:
    effects = VideoEffects(filter="sepia")
    muted = _plan(VideoProject((_clip("a.mp4"),), AudioSettings(mute=True), effects), tmp_path)
    assert "-an" in _args(muted)
    song = tmp_path / "song.mp3"
    replaced = _plan(
        VideoProject((_clip("a.mp4").with_trim(0, 30),), AudioSettings(0.8, False, song), effects),
        tmp_path,
    )
    args = _args(replaced)
    assert args.count("-i") == 2
    assert "1:a:0" in args
    assert _after(args, "-af") == "volume=0.800,apad"
    assert _after(args, "-t") == "30.000"


def test_single_clip_keeps_original_size_and_fps(tmp_path: Path) -> None:
    graph = _graph(
        _plan(VideoProject((_clip("a.mp4"),), effects=VideoEffects(filter="blur")), tmp_path)
    )
    assert "scale=" not in graph  # один клип не нормализуется
    assert "[0:v]gblur=sigma=3,format=yuv420p[vout]" in graph


def test_text_is_written_to_files_in_workdir(tmp_path: Path) -> None:
    effects = VideoEffects(texts=(Text("Привет\nмир", 20, 30, 40.0),))
    font = Path("C:/Windows/Fonts/arial.ttf")
    plan = _plan(VideoProject((_clip("a.mp4"),), effects=effects), tmp_path, font=font)
    written = tmp_path / "text00.txt"
    assert written.read_text(encoding="utf-8") == "Привет\nмир"
    assert written in plan.workdir_files
    assert "drawtext=textfile=" in _graph(plan)
    assert "Привет" not in " ".join(plan.steps[0].args)  # текст не попадает в командную строку


def test_frame_size_follows_rotation_metadata_and_is_even() -> None:
    portrait = MediaInfo(1920, 1080, 10.0, 30.0, "h264", "yuv420p", 90, AUDIO)
    assert VideoProject((Clip(Path("a.mp4"), portrait),)).frame_size == (1080, 1920)
    odd = MediaInfo(641, 361, 10.0, 30.0, "h264", "yuv420p", 0, AUDIO)
    assert VideoProject((Clip(Path("a.mp4"), odd),)).frame_size == (640, 360)


def test_crop_and_redacts_use_frame_coordinates(tmp_path: Path) -> None:
    effects = VideoEffects(
        crop=Rect(100, 50, 640, 360), redacts=(Redact(Rect(0, 0, 200, 100), "fill"),)
    )
    graph = _graph(_plan(VideoProject((_clip("a.mp4"),), effects=effects), tmp_path))
    assert graph.index("drawbox=x=0:y=0:w=200:h=100") < graph.index("crop=640:360:100:50")


def test_reencode_reason() -> None:
    plain = VideoProject((_clip("a.mp4").with_trim(1, 5),))
    assert plain.reencode_reason() is None
    assert plain.reencode_reason(precise=True) == "precise"
    assert VideoProject((_clip("a.mp4"),)).reencode_reason(precise=True) is None
    assert (
        VideoProject(plain.clips, effects=VideoEffects(rotation=90)).reencode_reason() == "effects"
    )
    assert VideoProject((_clip("a.mp4"), _clip("b.mp4", SMALL))).reencode_reason() == "clips"


@pytest.mark.parametrize("rotation", [0, 90])
def test_effects_summary(rotation: int) -> None:
    effects = VideoEffects(crop=Rect(0, 0, 10, 10), filter="blur", rotation=rotation)
    assert ("поворот 90°" in effects.describe()) == (rotation == 90)
    assert "кадр" in effects.describe()
    assert VideoEffects().describe() == []


def test_muted_join_has_no_audio_branches(tmp_path: Path) -> None:
    project = VideoProject(
        (_clip("a.mp4"), _clip("b.mp4", SMALL)),
        AudioSettings(mute=True),
        VideoEffects(filter="blur"),
    )
    plan = _plan(project, tmp_path)
    graph = _graph(plan)
    assert "[a0]" not in graph
    assert "concat=n=2:v=1:a=0[vcat]" in graph  # иначе выход acat остался бы неподключённым
    assert "-an" in _args(plan)
