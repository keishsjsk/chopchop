"""Модель блоков: резка, удаление, перестановка, края, миграция прежних клипов, история."""

from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.keyframes import junctions, needs_precise, precise_count, snap_back
from chopchop.core.video import (
    Clip,
    MoveBlock,
    ProjectHistory,
    RemoveBlock,
    RemoveRange,
    SplitAt,
    TrimBlock,
    VideoProject,
    cut_summary,
    legacy_blocks,
)
from chopchop.editor.video_session import VideoSession

INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))
FRAME = 0.04


def _clip(name: str = "a.mp4") -> Clip:
    return Clip(Path(name), INFO)


def _project(*clips: Clip) -> VideoProject:
    return VideoProject(clips or (_clip(),))


def _spans(project: VideoProject) -> list[tuple[str, float, float]]:
    return [(c.path.name, c.start, c.stop) for c in project.clips]


# --- блок ------------------------------------------------------------------------------------


def test_block_spans_whole_file_by_default() -> None:
    clip = _clip()
    assert clip.ranges == ((0.0, 60.0),) and clip.length == 60.0 and not clip.is_trimmed
    trimmed = clip.with_trim(5, 30)
    assert trimmed.ranges == ((5.0, 30.0),) and trimmed.is_trimmed
    assert clip.to_result(20.0) == 20.0 and trimmed.to_result(20.0) == 15.0


def test_block_edges_stay_inside_the_source_file() -> None:
    clip = _clip().with_trim(10, 20)
    assert clip.with_trim(-5, 70) == _clip()  # края тянутся до границ файла и не дальше
    assert clip.with_trim(15, 15).length == pytest.approx(0.1)  # короче 0,1 с не бывает
    assert _clip().with_trim(59.99, 99).length == pytest.approx(0.1)


def test_split_makes_two_adjacent_blocks_that_play_the_same() -> None:
    project = _project().split_at(20)
    assert _spans(project) == [("a.mp4", 0.0, 20.0), ("a.mp4", 20.0, 60.0)]
    assert project.duration == 60.0
    again = project.split_at(20.01)  # ближе кадра к существующему шву
    assert again == project
    assert project.split_at(0.0) == project and project.split_at(60.0) == project


def test_split_uses_result_time_across_blocks() -> None:
    project = _project(_clip("a.mp4").with_trim(10, 20), _clip("b.mp4").with_trim(0, 30))
    cut = project.split_at(15)  # 10 с первого блока и ещё 5 с во втором
    assert _spans(cut) == [("a.mp4", 10.0, 20.0), ("b.mp4", 0.0, 5.0), ("b.mp4", 5.0, 30.0)]


def test_remove_block_shifts_the_rest_and_keeps_the_last() -> None:
    project = _project().split_at(20).split_at(40)
    cut = RemoveBlock(1).apply(project)
    assert _spans(cut) == [("a.mp4", 0.0, 20.0), ("a.mp4", 40.0, 60.0)]
    assert cut.duration == 40.0
    single = _project()
    assert RemoveBlock(0).apply(single) == single  # последний блок удалить нельзя


def test_remove_range_splits_edges_and_closes_the_gap() -> None:
    project = _project()
    cut = RemoveRange(10, 20).apply(project)
    assert _spans(cut) == [("a.mp4", 0.0, 10.0), ("a.mp4", 20.0, 60.0)]
    assert RemoveRange(0, 60).apply(project) == project  # всё удалить нельзя
    assert RemoveRange(5, 5.0001).apply(project) == project


def test_move_block_reorders_without_losing_anything() -> None:
    project = _project().split_at(20).split_at(40)  # три блока: 0-20, 20-40, 40-60
    moved = MoveBlock(1, 2).apply(project)  # середина в конец
    assert _spans(moved) == [("a.mp4", 0.0, 20.0), ("a.mp4", 40.0, 60.0), ("a.mp4", 20.0, 40.0)]
    assert moved.duration == project.duration
    assert MoveBlock(1, 1).apply(project) == project
    assert MoveBlock(0, 9).apply(project) == project  # за границы не уходит


def test_trim_block_stretches_back_to_what_was_cut() -> None:
    project = _project().split_at(20).split_at(40)
    cut = RemoveBlock(1).apply(project)  # вырезали 20-40
    stretched = TrimBlock(0, 0.0, 30.0).apply(cut)  # левый блок растянули за шов вправо
    assert _spans(stretched)[0] == ("a.mp4", 0.0, 30.0)
    assert stretched.duration == 50.0  # итог длиннее: остаток сдвинулся вправо
    shortened = TrimBlock(2 - 1, 45.0, 60.0).apply(cut)
    assert _spans(shortened)[1] == ("a.mp4", 45.0, 60.0)


def test_locate_prefers_the_next_block_at_a_seam() -> None:
    project = _project(_clip("a.mp4").with_trim(0, 10), _clip("b.mp4").with_trim(20, 30))
    assert project.locate(5) == (0, 5.0)
    assert project.locate(10) == (1, 20.0)
    assert project.locate(10, end=True) == (0, 10.0)
    assert project.locate(999) == (1, 30.0)


def test_offsets_and_flat_ranges_follow_block_order() -> None:
    project = _project(_clip("a.mp4").with_trim(0, 10), _clip("b.mp4").with_trim(5, 15))
    assert project.offsets() == [0.0, 10.0]
    assert [(f.clip_index, f.start, f.stop) for f in project.flat_ranges()] == [
        (0, 0.0, 10.0),
        (1, 5.0, 15.0),
    ]


# --- сводка «вырезано» -----------------------------------------------------------------------


def test_cut_summary_counts_gaps_in_each_source() -> None:
    assert cut_summary(_project()) == (0, 0.0)
    cut = RemoveBlock(1).apply(_project().split_at(20).split_at(40))
    count, seconds = cut_summary(cut)
    assert count == 1 and seconds == pytest.approx(20.0)
    trimmed = _project(_clip().with_trim(10, 50))
    count, seconds = cut_summary(trimmed)  # начало и хвост
    assert count == 2 and seconds == pytest.approx(20.0)
    reordered = MoveBlock(0, 1).apply(_project().split_at(30))
    assert cut_summary(reordered) == (0, 0.0)  # ничего не потеряно, только порядок


# --- миграция прежних клипов -----------------------------------------------------------------


def test_legacy_clip_becomes_blocks() -> None:
    blocks = legacy_blocks(Path("a.mp4"), INFO)
    assert [(b.start, b.stop) for b in blocks] == [(0.0, 60.0)]
    trimmed = legacy_blocks(Path("a.mp4"), INFO, start=5.0, end=50.0)
    assert [(b.start, b.stop) for b in trimmed] == [(5.0, 50.0)]


def test_legacy_cuts_and_splits_become_blocks_in_order() -> None:
    blocks = legacy_blocks(
        Path("a.mp4"), INFO, start=0.0, end=-1.0, cuts=((10.0, 20.0),), splits=(40.0,)
    )
    assert [(b.start, b.stop) for b in blocks] == [(0.0, 10.0), (20.0, 40.0), (40.0, 60.0)]
    assert sum(b.length for b in blocks) == 50.0  # итог тот же, что был у клипа с вырезом


# --- сессия и история ------------------------------------------------------------------------


def test_operations_are_single_history_steps() -> None:
    session = VideoSession(_project())
    session.cut(SplitAt(30))
    session.cut(RemoveBlock(1))
    assert _spans(session.project) == [("a.mp4", 0.0, 30.0)]
    session.cut(TrimBlock(0, 0.0, 45.0))
    assert session.project.duration == 45.0
    session.undo()  # отмена возвращает именно растяжение края
    assert session.project.duration == 30.0
    session.undo()
    assert len(session.project.clips) == 2
    session.undo()
    assert session.project == _project() and not session.can_undo
    session.redo()
    assert len(session.project.clips) == 2
    session.cut(SplitAt(30.001))  # шов уже есть: ничего не меняется, история не засоряется
    session.cut(RemoveRange(0, 60))  # всё удалить нельзя
    session.undo()
    assert not session.can_undo


def test_moving_blocks_is_undoable() -> None:
    session = VideoSession(_project().split_at(20).split_at(40))
    session.cut(MoveBlock(1, 2))
    assert [c.start for c in session.project.clips] == [0.0, 40.0, 20.0]
    session.undo()
    assert [c.start for c in session.project.clips] == [0.0, 20.0, 40.0]


def test_history_marks_modified_only_when_the_result_differs() -> None:
    history = ProjectHistory(_project())
    history.push(RemoveRange(10, 20).apply(history.current))
    assert history.modified
    history.undo()
    assert not history.modified


# --- ключевые кадры --------------------------------------------------------------------------

KEYFRAMES = [0.0, 2.0, 4.0, 6.0, 8.0]


def test_snap_goes_back_to_the_previous_keyframe() -> None:
    assert snap_back(KEYFRAMES, 5.0) == 4.0
    assert snap_back(KEYFRAMES, 4.0) == 4.0 and snap_back(KEYFRAMES, 3.9995) == 4.0
    assert snap_back(KEYFRAMES, 0.5) == 0.0
    assert snap_back([], 5.0) == 5.0  # без данных привязки нет


def test_needs_precise_when_start_is_not_a_keyframe() -> None:
    assert not needs_precise(KEYFRAMES, 4.0, FRAME)
    assert needs_precise(KEYFRAMES, 4.5, FRAME)
    assert not needs_precise([], 4.5, FRAME)


def test_junctions_report_every_block_start() -> None:
    project = RemoveRange(4.5, 7.0).apply(_project())
    found = junctions(project, {Path("a.mp4"): KEYFRAMES})
    assert [(j.start, j.snapped, j.precise) for j in found] == [(0.0, 0.0, False), (7.0, 6.0, True)]
    assert found[1].shift == pytest.approx(1.0)
    assert precise_count(project, {Path("a.mp4"): KEYFRAMES}) == 1
    assert precise_count(project, {}) == 0
