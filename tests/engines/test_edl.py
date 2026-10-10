"""EDL предпросмотра монтажа: порядок кусков, слияние соседей, экранирование путей."""

from pathlib import Path

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.video import Clip, MoveBlock, RemoveBlock, VideoProject
from chopchop.engines.edl import edl_entries, edl_source
from chopchop.ui.video_editor_page import cut_text, plural_form

INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _project(name: str = "a.mp4") -> VideoProject:
    return VideoProject((Clip(Path(name), INFO),))


def test_whole_file_is_loaded_as_a_plain_path() -> None:
    assert edl_source(_project()) == "a.mp4"


def test_a_split_alone_does_not_change_what_is_played() -> None:
    assert edl_source(_project().split_at(20)) == edl_source(_project())
    assert edl_entries(_project().split_at(20)) == [(Path("a.mp4"), 0.0, 60.0)]


def test_blocks_become_edl_lines_in_playing_order() -> None:
    project = MoveBlock(1, 2).apply(_project().split_at(20).split_at(40))
    source = edl_source(project)
    assert source == (
        "edl://%5%a.mp4,0.000000,20.000000;%5%a.mp4,40.000000,20.000000;"
        "%5%a.mp4,20.000000,20.000000"
    )


def test_removed_block_leaves_a_gap_in_the_source_not_in_the_list() -> None:
    project = RemoveBlock(1).apply(_project().split_at(20).split_at(40))
    assert [(a, b) for _p, a, b in edl_entries(project)] == [(0.0, 20.0), (40.0, 60.0)]


def test_path_length_prefix_protects_commas_and_semicolons() -> None:
    name = "a,b;c.mp4"  # 9 байт
    cut = RemoveBlock(1).apply(_project(name).split_at(10).split_at(30))
    assert edl_source(cut).startswith("edl://%9%a,b;c.mp4,0.000000,10.000000;%9%a,b;c.mp4,")
    cyrillic = edl_source(RemoveBlock(1).apply(_project("видео.mp4").split_at(10).split_at(30)))
    assert cyrillic.startswith("edl://%14%видео.mp4,")  # длина в байтах UTF-8, а не в буквах


def test_russian_and_english_plural_forms() -> None:
    forms = {n: plural_form(n, "ru") for n in (1, 2, 4, 5, 11, 12, 21, 22, 25)}
    assert forms == {1: 0, 2: 1, 4: 1, 5: 2, 11: 2, 12: 2, 21: 0, 22: 1, 25: 2}
    assert plural_form(1, "en") == 0 and plural_form(2, "en") == 2
    assert cut_text(2, 12.0, "ru") == "2 фрагмента, −0:12"
    assert cut_text(5, 65.0, "ru") == "5 фрагментов, −1:05"
