"""Команды ffmpeg для вырезов из середины: быстрый список склейки и точный фильтр."""

from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.video import AudioSettings, Clip, VideoProject, legacy_blocks
from chopchop.engines.keyframes import parse_keyframes
from chopchop.engines.video_engine import build_plan, ranges_concat_list

FFMPEG = Path("/opt/ffmpeg")
INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))
SILENT = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, None)


def _cuts(
    name: str, info: MediaInfo, start: float = 0.0, *cuts: tuple[float, float]
) -> tuple[Clip, ...]:
    """Блоки файла без вырезанных кусков (вырезы заданы во времени файла)."""
    return legacy_blocks(Path(name), info, start=start, cuts=tuple(cuts))


def _plan(project: VideoProject, tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    return build_plan(project, tmp_path / "out.mp4", FFMPEG, tmp_path, **kwargs)


def _listing(tmp_path: Path) -> list[str]:
    return (tmp_path / "list.txt").read_text(encoding="utf-8").splitlines()


def test_fast_mode_is_one_call_with_inpoint_and_outpoint_per_range(tmp_path: Path) -> None:
    plan = _plan(VideoProject(_cuts("a.mp4", INFO, 0.0, (10.0, 20.0))), tmp_path)
    (step,) = plan.steps
    assert "-c" in step.args and step.args[step.args.index("-c") + 1] == "copy"
    assert _listing(tmp_path) == [
        "ffconcat version 1.0",
        "file 'a.mp4'",
        "outpoint 10.000000",
        "file 'a.mp4'",
        "inpoint 20.000000",
    ]
    assert step.duration == pytest.approx(50.0)
    assert plan.workdir_files == (tmp_path / "list.txt",) and not plan.reencodes_video


def test_fast_mode_snaps_range_starts_to_keyframes(tmp_path: Path) -> None:
    blocks = _cuts("a.mp4", INFO, 0.0, (10.0, 21.5))
    keyframes = {Path("a.mp4"): [0.0, 5.0, 10.0, 20.0, 25.0]}
    _plan(VideoProject(blocks), tmp_path, keyframes=keyframes)
    assert "inpoint 20.000000" in _listing(tmp_path)  # 21.5 -> ключевой кадр 20.0
    assert "outpoint 10.000000" in _listing(tmp_path)


def test_several_cuts_and_clips_of_one_file_in_one_list(tmp_path: Path) -> None:
    first = _cuts("a.mp4", INFO, 0.0, (10.0, 20.0), (30.0, 40.0))
    second = Clip(Path("a.mp4"), INFO).with_trim(5, 15)  # тот же файл ещё раз
    plan = _plan(VideoProject((*first, second)), tmp_path)
    assert len(plan.steps) == 1
    files = [line for line in _listing(tmp_path) if line.startswith("file")]
    assert files == ["file 'a.mp4'"] * 4
    assert plan.steps[0].duration == pytest.approx(10 + 10 + 20 + 10)


def test_different_files_go_through_a_common_container(tmp_path: Path) -> None:
    """У mp4 и mkv разные единицы времени: напрямую склеенные, они ломают метки времени."""
    first = _cuts("a.mp4", INFO, 0.0, (10.0, 20.0))
    second = Clip(Path("b.mkv"), INFO)
    plan = _plan(VideoProject((*first, second)), tmp_path)
    assert [s.output.name for s in plan.steps] == ["clip000.mkv", "clip001.mkv", "out.mp4"]
    piece_list = (tmp_path / "clip000.txt").read_text(encoding="utf-8").splitlines()
    assert piece_list == [
        "ffconcat version 1.0",
        "file 'a.mp4'",
        "outpoint 10.000000",
        "file 'a.mp4'",
        "inpoint 20.000000",
    ]  # соседние блоки одного файла — одним списком в первом шаге
    assert "concat" not in plan.steps[1].args  # одиночный блок копируется как раньше


def test_list_text_escapes_quotes() -> None:
    from pathlib import PurePosixPath

    text = ranges_concat_list([(PurePosixPath("/m/it's.mp4"), 1.5, 3.0)])
    assert "file '/m/it'\\''s.mp4'" in text
    assert "inpoint 1.500000" in text and "outpoint 3.000000" in text


def test_audio_settings_stay_in_the_same_call(tmp_path: Path) -> None:
    blocks = _cuts("a.mp4", INFO, 0.0, (10.0, 20.0))
    plan = _plan(VideoProject(blocks, AudioSettings(volume=0.5)), tmp_path)
    args = list(plan.steps[0].args)
    assert args[args.index("-af") + 1] == "volume=0.500" and plan.reencodes_audio


def test_precise_mode_trims_each_block_from_its_own_input(tmp_path: Path) -> None:
    blocks = _cuts("a.mp4", INFO, 5.0, (20.0, 30.0))  # блоки 5-20 и 30-60
    plan = _plan(VideoProject(blocks), tmp_path, precise=True)
    (step,) = plan.steps
    args = list(step.args)
    graph = args[args.index("-filter_complex") + 1]
    inputs = [i for i, value in enumerate(args) if value == "-i"]
    assert len(inputs) == 2  # блок — отдельный вход со своими -ss и -to
    first, second = args[: inputs[0] + 2], args[inputs[0] + 2 : inputs[1] + 2]
    assert first[first.index("-ss") + 1] == "5.000" and first[first.index("-to") + 1] == "20.000"
    assert second[second.index("-ss") + 1] == "30.000"
    assert "-to" not in second  # второй блок идёт до конца файла
    assert "concat=n=2:v=1:a=1[vcat][acat]" in graph
    assert plan.reencodes_video and step.duration == pytest.approx(45.0)


def test_precise_mode_without_cuts_is_unchanged_single_range(tmp_path: Path) -> None:
    clip = Clip(Path("a.mp4"), INFO).with_trim(5, 50)
    plan = _plan(VideoProject((clip,)), tmp_path, precise=True)
    graph = list(plan.steps[0].args)[list(plan.steps[0].args).index("-filter_complex") + 1]
    assert "split" not in graph and "trim=" not in graph and "concat" not in graph


def test_precise_cut_of_a_silent_clip_has_no_audio_graph(tmp_path: Path) -> None:
    blocks = _cuts("a.mp4", SILENT, 0.0, (10.0, 20.0))
    plan = _plan(VideoProject(blocks), tmp_path, precise=True)
    args = list(plan.steps[0].args)
    graph = args[args.index("-filter_complex") + 1]
    assert "asplit" not in graph and "concat=n=2:v=1:a=0" in graph and "-an" in args


def test_precise_cut_with_a_second_clip_mixes_pieces_in_order(tmp_path: Path) -> None:
    first = _cuts("a.mp4", INFO, 0.0, (10.0, 20.0))
    second = Clip(Path("b.mp4"), INFO).with_trim(0, 10)
    plan = _plan(VideoProject((*first, second)), tmp_path, precise=True)
    graph = list(plan.steps[0].args)[list(plan.steps[0].args).index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in graph
    order = [graph.index(f"[v{i}]") for i in range(3)]
    assert order == sorted(order)


def test_effects_run_after_the_joined_ranges(tmp_path: Path) -> None:
    from chopchop.core.video import VideoEffects

    blocks = _cuts("a.mp4", INFO, 0.0, (10.0, 20.0))
    project = VideoProject(blocks, effects=VideoEffects(filter="grayscale"))
    plan = _plan(project, tmp_path)  # быстрый режим невозможен: эффекты
    graph = list(plan.steps[0].args)[list(plan.steps[0].args).index("-filter_complex") + 1]
    assert graph.index("concat=n=2") < graph.index("hue=s=0")


def test_parse_keyframes_reads_only_key_packets() -> None:
    output = "0.000000,K__\n0.040000,___\n2.000000,K_\n1.960000,___\nN/A,K__\n4.000000,K__\n"
    assert parse_keyframes(output) == (0.0, 2.0, 4.0)
