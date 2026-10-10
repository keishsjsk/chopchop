"""Время показа текста и областей: пересчёт после вырезов и перевод во время файла."""

from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text, is_timed
from chopchop.core.timing import (
    result_windows_to_source,
    retime,
    to_result,
    to_source,
)
from chopchop.core.video import Clip, RemoveRange, VideoEffects, VideoProject
from chopchop.editor.video_session import VideoSession

INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _project(effects: VideoEffects | None = None, clips: int = 1) -> VideoProject:
    items = tuple(Clip(Path(f"{n}.mp4"), INFO) for n in "ab"[:clips])
    return VideoProject(items, effects=effects or VideoEffects())


def test_default_is_the_whole_video_and_photo_fields_stay_default() -> None:
    assert not is_timed(Text("x", 0, 0)) and not is_timed(Redact(Rect(0, 0, 5, 5)))
    assert is_timed(Text("x", 0, 0, show_from=1.0)) and is_timed(Text("x", 0, 0, show_to=5.0))


def test_result_time_to_source_time_across_a_cut() -> None:
    project = _project()
    cut = project.with_clip(0, project.clips[0].remove_span(10, 20))
    assert to_source(cut, 5.0) == (0, 5.0)
    assert to_source(cut, 15.0) == (0, 25.0)  # после выреза время файла сдвинуто на 10
    assert to_result(cut, 0, 25.0) == 15.0 and to_result(cut, 0, 15.0) == 10.0  # внутри выреза
    # на стыке: начало берёт следующий кусок, конец — прежний
    assert to_source(cut, 10.0) == (0, 20.0)
    assert to_source(cut, 10.0, end=True) == (0, 10.0)


def test_window_is_split_into_source_pieces_around_a_cut() -> None:
    project = _project()
    cut = project.with_clip(0, project.clips[0].remove_span(10, 20))
    assert result_windows_to_source(cut, 0, 5.0, 15.0) == [(5.0, 10.0), (20.0, 25.0)]
    assert result_windows_to_source(cut, 0, 0.0, -1.0) == [(0.0, 10.0), (20.0, 60.0)]
    assert result_windows_to_source(cut, 0, 12.0, 14.0) == [(22.0, 24.0)]


def test_windows_follow_their_clip_in_a_two_clip_project() -> None:
    project = _project(clips=2)  # по 60 секунд
    assert result_windows_to_source(project, 0, 50.0, 70.0) == [(50.0, 60.0)]
    assert result_windows_to_source(project, 1, 50.0, 70.0) == [(0.0, 10.0)]
    assert result_windows_to_source(project, 1, 0.0, 30.0) == []


def test_cut_before_the_window_moves_it_earlier() -> None:
    effects = VideoEffects(texts=(Text("Привет", 5, 5, show_from=30.0, show_to=40.0),))
    old = _project(effects)
    new = old.with_clip(0, old.clips[0].remove_span(10, 20))
    fitted, notes = retime(old, new)
    text = fitted.effects.texts[0]
    assert (text.show_from, text.show_to) == (20.0, 30.0) and notes == []


def test_cut_inside_the_window_shortens_it_and_after_it_changes_nothing() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(0, 0, 5, 5), show_from=10.0, show_to=30.0),))
    old = _project(effects)
    inside = retime(old, old.with_clip(0, old.clips[0].remove_span(15, 25)))[0]
    assert (inside.effects.redacts[0].show_from, inside.effects.redacts[0].show_to) == (10.0, 20.0)
    after = retime(old, old.with_clip(0, old.clips[0].remove_span(40, 50)))[0]
    assert (after.effects.redacts[0].show_from, after.effects.redacts[0].show_to) == (10.0, 30.0)


def test_open_end_stays_open_and_default_effects_are_untouched() -> None:
    effects = VideoEffects(
        texts=(Text("a", 0, 0, show_from=30.0), Text("b", 0, 0)),
    )
    old = _project(effects)
    new = old.with_clip(0, old.clips[0].remove_span(0, 10))
    fitted, _notes = retime(old, new)
    first, second = fitted.effects.texts
    assert (first.show_from, first.show_to) == (20.0, -1.0)  # конец «до конца ролика» остался
    assert second == Text("b", 0, 0)


def test_window_removed_entirely_is_reported() -> None:
    effects = VideoEffects(texts=(Text("Скрытый", 0, 0, show_from=12.0, show_to=18.0),))
    old = _project(effects)
    new = old.with_clip(0, old.clips[0].remove_span(10, 20))
    fitted, notes = retime(old, new)
    assert [n.kind for n in notes] == ["collapsed"] and notes[0].label == "Скрытый"
    assert fitted.effects.texts[0].show_to - fitted.effects.texts[0].show_from < 0.04


def test_changing_the_clip_list_clamps_and_warns() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=70.0, show_to=100.0),))
    old = _project(effects, clips=2)
    new = VideoProject(old.clips[:1], effects=old.effects)  # убрали второй клип: итог 60 с
    fitted, notes = retime(old, new)
    assert [n.kind for n in notes].count("clamped") == 1
    assert fitted.effects.texts[0].show_from == 60.0


def test_session_applies_the_retime_in_one_history_step_and_reports() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=30.0, show_to=40.0),))
    session = VideoSession(_project(effects))
    seen: list[list[object]] = []
    session.timeNotes.connect(seen.append)
    session.cut(RemoveRange(0, 10, 20))
    assert session.project.effects.texts[0].show_from == 20.0
    assert seen == []
    session.undo()  # отмена возвращает и время показа
    assert session.project.effects.texts[0].show_from == 30.0
    session.cut(RemoveRange(0, 28, 45))
    assert len(seen) == 1 and seen[0][0].kind == "collapsed"  # type: ignore[attr-defined]


@pytest.mark.parametrize(("a", "b"), [(0.0, -1.0), (1.0, -1.0), (1.0, 3.0), (0.0, 3.0)])
def test_untouched_windows_survive_edge_trims_only_when_inside(a: float, b: float) -> None:
    text = Text("x", 0, 0, show_from=a, show_to=b)
    old = _project(VideoEffects(texts=(text,)))
    fitted, _ = retime(old, old)
    assert fitted.effects.texts[0] == text
