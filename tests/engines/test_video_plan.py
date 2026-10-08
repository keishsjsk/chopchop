"""Построение команд ffmpeg: сравнение аргументов, без запуска ffmpeg."""

from pathlib import Path

import pytest

from quickedit.core.document import AudioInfo, MediaInfo
from quickedit.core.video import AudioSettings, Clip, VideoProject
from quickedit.engines.video_engine import (
    ExportPlanError,
    build_plan,
    concat_list,
    default_video_output,
    thumbnail_args,
)

FFMPEG = Path("/opt/ffmpeg")
INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))
SILENT = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, None)


def _clip(name: str = "a.mp4", info: MediaInfo = INFO) -> Clip:
    return Clip(Path(name), info)


def _args(plan_args: tuple[str, ...]) -> list[str]:
    return list(plan_args)


def _plan(project: VideoProject, tmp_path: Path, dest: str = "out.mp4"):  # type: ignore[no-untyped-def]
    return build_plan(project, tmp_path / dest, FFMPEG, tmp_path)


def _after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_single_clip_without_changes_is_a_remux_without_metadata(tmp_path: Path) -> None:
    plan = _plan(VideoProject((_clip(),)), tmp_path)
    (step,) = plan.steps
    args = _args(step.args)
    assert "-ss" not in args
    assert "-to" not in args
    assert _after(args, "-c") == "copy"
    assert args[args.index("-map_metadata") + 1] == "-1"
    assert "-movflags" in args
    assert args[-1] == str(tmp_path / "out.mp4")
    assert not plan.reencodes_audio


def test_trim_uses_input_seeking_and_copy(tmp_path: Path) -> None:
    clip = _clip().with_trim(5, 30)
    plan = _plan(VideoProject((clip,)), tmp_path)
    args = _args(plan.steps[0].args)
    assert args.index("-ss") < args.index("-i")
    assert _after(args, "-ss") == "5.000"
    assert _after(args, "-to") == "30.000"
    assert args[args.index("-i") + 1] == "a.mp4"
    assert _after(args, "-c") == "copy"
    assert plan.steps[0].duration == pytest.approx(25.0)


def test_only_end_trimmed_has_no_ss(tmp_path: Path) -> None:
    plan = _plan(VideoProject((_clip().with_trim(0, 10),)), tmp_path)
    args = _args(plan.steps[0].args)
    assert "-ss" not in args
    assert _after(args, "-to") == "10.000"


def test_mute_drops_audio_but_copies_video(tmp_path: Path) -> None:
    project = VideoProject((_clip(),), AudioSettings(mute=True))
    plan = _plan(project, tmp_path)
    args = _args(plan.steps[0].args)
    assert "-an" in args
    assert _after(args, "-c:v") == "copy"
    assert "0:a?" not in args
    assert not plan.reencodes_audio


def test_volume_reencodes_only_audio(tmp_path: Path) -> None:
    project = VideoProject((_clip(),), AudioSettings(volume=0.5))
    plan = _plan(project, tmp_path)
    args = _args(plan.steps[0].args)
    assert _after(args, "-c:v") == "copy"
    assert _after(args, "-c:a") == "aac"
    assert _after(args, "-af") == "volume=0.500"
    assert plan.reencodes_audio


def test_replacement_audio_becomes_second_input(tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    project = VideoProject((_clip().with_trim(0, 20),), AudioSettings(volume=2.0, replacement=song))
    plan = _plan(project, tmp_path)
    args = _args(plan.steps[0].args)
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    assert inputs == ["a.mp4", str(song)]
    assert "1:a:0" in args
    assert _after(args, "-af") == "volume=2.000,apad"
    assert _after(args, "-t") == "20.000"  # apad бесконечен, длину задаёт видео
    assert plan.reencodes_audio


def test_mute_overrides_replacement(tmp_path: Path) -> None:
    project = VideoProject((_clip(),), AudioSettings(mute=True, replacement=tmp_path / "song.mp3"))
    args = _args(_plan(project, tmp_path).steps[0].args)
    assert "-an" in args
    assert "1:a:0" not in args


def test_video_without_audio_stays_silent_by_default(tmp_path: Path) -> None:
    project = VideoProject((_clip(info=SILENT),), AudioSettings(volume=2.0))
    args = _args(_plan(project, tmp_path).steps[0].args)
    assert "-an" in args


def test_concat_normalizes_every_clip_then_joins(tmp_path: Path) -> None:
    project = VideoProject((_clip("a.mp4").with_trim(10, 20), _clip("b.mp4")))
    plan = _plan(project, tmp_path)
    assert len(plan.steps) == 3
    first, second, join = plan.steps
    assert first.output == tmp_path / "clip000.mkv"
    assert second.output == tmp_path / "clip001.mkv"
    assert _after(_args(first.args), "-ss") == "10.000"
    assert "-ss" not in second.args  # второй клип не обрезан, но тоже копируется в mkv
    assert "-avoid_negative_ts" in first.args
    join_args = _args(join.args)
    assert _after(join_args, "-f") == "concat"
    assert _after(join_args, "-c") == "copy"
    listing = (tmp_path / "list.txt").read_text(encoding="utf-8").splitlines()
    assert listing == [
        f"file '{(tmp_path / 'clip000.mkv').as_posix()}'",
        f"file '{(tmp_path / 'clip001.mkv').as_posix()}'",
    ]
    assert join.duration == pytest.approx(70.0)
    assert set(plan.workdir_files) == {
        tmp_path / "clip000.mkv",
        tmp_path / "clip001.mkv",
        tmp_path / "list.txt",
    }


def test_concat_applies_audio_settings_in_final_step(tmp_path: Path) -> None:
    project = VideoProject((_clip("a.mp4"), _clip("b.mp4")), AudioSettings(volume=0.8))
    plan = _plan(project, tmp_path)
    assert len(plan.steps) == 3  # два временных клипа и склейка
    args = _args(plan.steps[-1].args)
    assert _after(args, "-af") == "volume=0.800"
    assert _after(args, "-c:v") == "copy"


def test_output_cannot_overwrite_source(tmp_path: Path) -> None:
    source = tmp_path / "a.mp4"
    project = VideoProject((Clip(source, INFO),))
    with pytest.raises(ExportPlanError, match="overwrite"):
        build_plan(project, source, FFMPEG, tmp_path)
    song = tmp_path / "song.mp3"
    with_song = VideoProject((_clip(),), AudioSettings(replacement=song))
    with pytest.raises(ExportPlanError):
        build_plan(with_song, song, FFMPEG, tmp_path)


def test_empty_project_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ExportPlanError):
        build_plan(VideoProject(()), tmp_path / "x.mp4", FFMPEG, tmp_path)


def test_mkv_has_no_faststart(tmp_path: Path) -> None:
    args = _args(_plan(VideoProject((_clip(),)), tmp_path, "out.mkv").steps[0].args)
    assert "-movflags" not in args


def test_no_shell_is_involved_for_odd_file_names(tmp_path: Path) -> None:
    name = "a b'; rm -rf $HOME.mp4"
    plan = _plan(VideoProject((_clip(name),)), tmp_path)
    assert name in plan.steps[0].args  # имя файла — один аргумент, а не часть командной строки


def test_concat_list_escapes_quotes_and_backslashes() -> None:
    text = concat_list([Path("C:\\media\\it's.mp4")])
    assert "\\" not in text.replace("'\\''", "")
    assert "it'\\''s" in text


def test_thumbnail_args_seek_before_input() -> None:
    args = thumbnail_args(FFMPEG, Path("a.mp4"), 12.3456)
    assert args.index("-ss") < args.index("-i")
    assert args[args.index("-ss") + 1] == "12.346"
    assert args[-1] == "-"


def test_default_video_output_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    first = default_video_output(source)
    assert first == tmp_path / "movie_edited.mkv"
    first.write_bytes(b"x")
    assert default_video_output(source) == tmp_path / "movie_edited (2).mkv"
    assert default_video_output(tmp_path / "clip.avi") == tmp_path / "clip_edited.mkv"
    assert default_video_output(tmp_path / "c.mov", ".mp4") == tmp_path / "c_edited.mp4"
