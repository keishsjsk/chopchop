"""Модель вырезов: разрезы, удаление из середины, слияние, миграция обрезки, история."""

from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.keyframes import junctions, needs_precise, precise_count, snap_back
from chopchop.core.video import (
    Clip,
    ProjectHistory,
    RemoveRange,
    RestoreRange,
    SplitAt,
    VideoProject,
)
from chopchop.editor.video_session import VideoSession

INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))
FRAME = 0.04


def _clip(name: str = "a.mp4") -> Clip:
    return Clip(Path(name), INFO)


# --- миграция обрезки ------------------------------------------------------------------------


def test_old_trim_is_a_single_range() -> None:
    clip = Clip(Path("a.mp4"), INFO, start=2.0)  # так создавалась обрезка раньше
    assert clip.ranges == ((2.0, 60.0),) and clip.is_trimmed and not clip.has_cuts
    assert clip.length == 58.0
    trimmed = _clip().with_trim(5, 30)
    assert trimmed.ranges == ((5.0, 30.0),) and trimmed.stop == 30.0
    assert _clip().ranges == ((0.0, 60.0),) and not _clip().is_trimmed


def test_trim_edges_keep_cuts_inside_and_drop_the_rest() -> None:
    cut = _clip().remove_span(20, 30)
    narrowed = cut.with_trim(25, 50)  # вырез съел левый край: остаётся (30, 50)
    assert narrowed.ranges == ((30.0, 50.0),)  # вырез съел левый край обрезки
    inside = cut.with_trim(10, 50)
    assert inside.ranges == ((10.0, 20.0), (30.0, 50.0))
    wider = inside.with_trim(0, 60)
    assert wider.ranges == ((0.0, 20.0), (30.0, 60.0))  # края вернулись, вырез остался


# --- разрез и удаление -----------------------------------------------------------------------


def test_split_adds_segments_without_changing_the_result() -> None:
    clip = _clip().split_at(20).split_at(40)
    assert clip.ranges == ((0.0, 60.0),) and clip.length == 60.0
    assert clip.segments() == ((0.0, 20.0), (20.0, 40.0), (40.0, 60.0))
    assert clip.split_at(20.01) == clip  # ближе кадра к существующему разрезу
    assert clip.split_at(0.0) == clip and clip.split_at(60.0) == clip  # на краях разрезать нечего
    assert clip.split_at(75.0) == clip  # вне клипа


def test_removing_the_middle_shifts_the_rest_and_shows_a_ghost() -> None:
    clip = _clip().remove_span(10, 20)
    assert clip.ranges == ((0.0, 10.0), (20.0, 60.0))
    assert clip.length == 50.0 and clip.cuts == ((10.0, 20.0),)
    assert clip.ghosts() == ((10.0, 20.0),)
    assert clip.to_result(5.0) == 5.0 and clip.to_result(25.0) == 15.0  # после выреза — сдвиг
    assert clip.to_result(60.0) == 50.0


def test_removing_a_selected_segment_after_split() -> None:
    clip = _clip().split_at(20).split_at(40)
    middle = clip.segments()[1]
    after = clip.remove_span(*middle)
    assert after.ranges == ((0.0, 20.0), (40.0, 60.0))
    assert after.splits == ()  # метки внутри удалённого пропали


def test_removing_at_the_edges_is_a_trim() -> None:
    assert _clip().remove_span(0, 10).ranges == ((10.0, 60.0),)
    assert _clip().remove_span(50, 60).ranges == ((0.0, 50.0),)
    assert _clip().remove_span(0, 10).start == 10.0


def test_cannot_remove_everything() -> None:
    clip = _clip()
    assert clip.remove_span(0, 60) == clip
    assert clip.remove_span(-5, 100) == clip
    two = clip.remove_span(10, 50)
    assert two.remove_span(0, 60) == two


def test_adjacent_cuts_merge_and_restoring_gives_the_original() -> None:
    clip = _clip().remove_span(10, 20).remove_span(20, 30)
    assert clip.ranges == ((0.0, 10.0), (30.0, 60.0)) and clip.cuts == ((10.0, 30.0),)
    overlapping = _clip().remove_span(10, 25).remove_span(20, 30)
    assert overlapping.cuts == ((10.0, 30.0),)
    assert clip.restore_span(10, 30) == _clip()
    assert clip.restore_span(10, 20).ranges == ((0.0, 20.0), (30.0, 60.0))  # часть призрака


def test_minimum_range_is_one_frame() -> None:
    clip = _clip().remove_span(10, 59.99)  # от хвоста остался бы кусок короче кадра
    assert clip.ranges == ((0.0, 10.0),)  # а такой кусок не живёт: он удалён целиком
    tiny = _clip().remove_span(10.0, 10.01)
    assert tiny == _clip()  # короче половины кадра: вырезать нечего
    one_frame = _clip().remove_span(0, 59.96)
    assert one_frame.ranges == ((59.96, 60.0),) and one_frame.length >= FRAME - 1e-6


def test_restoring_an_edge_ghost_extends_the_trim() -> None:
    trimmed = _clip().with_trim(10, 50)
    assert trimmed.ghosts() == ((0.0, 10.0), (50.0, 60.0))
    assert trimmed.restore_span(0, 10) == _clip().with_trim(0, 50)
    assert trimmed.restore_span(0, 60).ranges == ((0.0, 60.0),)


def test_reset_returns_the_whole_clip() -> None:
    clip = _clip().with_trim(5, 50).remove_span(10, 20).split_at(30)
    assert clip.reset() == _clip()


# --- итог склейки и история ------------------------------------------------------------------


def test_flat_ranges_follow_clip_order() -> None:
    project = VideoProject((_clip("a.mp4").remove_span(10, 20), _clip("b.mp4").with_trim(5, 15)))
    flat = project.flat_ranges()
    assert [(f.clip_index, f.start, f.stop) for f in flat] == [
        (0, 0.0, 10.0),
        (0, 20.0, 60.0),
        (1, 5.0, 15.0),
    ]
    assert project.duration == pytest.approx(60.0)


def test_operations_are_single_history_steps() -> None:
    session = VideoSession(VideoProject((_clip(),)))
    session.cut(SplitAt(0, 30))
    session.cut(RemoveRange(0, 30, 60))
    assert session.project.clips[0].ranges == ((0.0, 30.0),)
    assert session.project.duration == 30.0
    session.cut(RestoreRange(0, 30, 60))
    assert session.project.clips[0].ranges == ((0.0, 60.0),)
    session.undo()  # отмена возвращает именно удаление
    assert session.project.clips[0].ranges == ((0.0, 30.0),)
    session.undo()
    assert session.project.clips[0].splits == (30.0,)
    session.undo()
    assert session.project.clips[0] == _clip()
    assert not session.can_undo
    session.redo()
    assert session.project.clips[0].splits == (30.0,)
    session.cut(SplitAt(0, 30))  # то же самое ничего не меняет и историю не засоряет
    session.cut(RemoveRange(0, 0, 60))  # всё удалить нельзя
    session.undo()
    assert not session.can_undo


def test_history_marks_modified_only_when_the_result_differs() -> None:
    history = ProjectHistory(VideoProject((_clip(),)))
    history.push(RemoveRange(0, 10, 20).apply(history.current))
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


def test_junctions_report_every_range_start() -> None:
    clip = Clip(Path("a.mp4"), INFO).remove_span(4.5, 7.0)
    project = VideoProject((clip,))
    found = junctions(project, {Path("a.mp4"): KEYFRAMES})
    assert [(j.start, j.snapped, j.precise) for j in found] == [(0.0, 0.0, False), (7.0, 6.0, True)]
    assert found[1].shift == pytest.approx(1.0)
    assert precise_count(project, {Path("a.mp4"): KEYFRAMES}) == 1
    assert precise_count(project, {}) == 0
