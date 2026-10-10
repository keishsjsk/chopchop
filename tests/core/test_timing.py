"""Время показа текста и областей: пересчёт после правок блоков и позиция воспроизведения."""

from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text, is_timed
from chopchop.core.timing import map_position, retime, to_result, to_source
from chopchop.core.video import (
    Clip,
    MoveBlock,
    RemoveBlock,
    RemoveRange,
    TrimBlock,
    VideoEffects,
    VideoProject,
)
from chopchop.editor.video_session import VideoSession

INFO = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _project(effects: VideoEffects | None = None, clips: int = 1) -> VideoProject:
    items = tuple(Clip(Path(f"{n}.mp4"), INFO) for n in "ab"[:clips])
    return VideoProject(items, effects=effects or VideoEffects())


def _window(project: VideoProject, kind: str = "text") -> tuple[float, float]:
    item = project.effects.texts[0] if kind == "text" else project.effects.redacts[0]
    return item.show_from, item.show_to


def test_default_is_the_whole_video_and_photo_fields_stay_default() -> None:
    assert not is_timed(Text("x", 0, 0)) and not is_timed(Redact(Rect(0, 0, 5, 5)))
    assert is_timed(Text("x", 0, 0, show_from=1.0)) and is_timed(Text("x", 0, 0, show_to=5.0))


def test_result_time_to_source_time_across_a_removed_block() -> None:
    cut = RemoveRange(10, 20).apply(_project())
    assert to_source(cut, 5.0) == (0, 5.0)
    assert to_source(cut, 15.0) == (1, 25.0)  # после выреза время файла сдвинуто на 10
    assert to_result(cut, 1, 25.0) == 15.0 and to_result(cut, 1, 15.0) == 10.0  # левее блока
    # на шве: начало берёт следующий блок, конец прежний
    assert to_source(cut, 10.0) == (1, 20.0)
    assert to_source(cut, 10.0, end=True) == (0, 10.0)


def test_cut_before_the_window_moves_it_earlier() -> None:
    effects = VideoEffects(texts=(Text("Привет", 5, 5, show_from=30.0, show_to=40.0),))
    old = _project(effects)
    fitted, notes = retime(old, RemoveRange(10, 20).apply(old))
    assert _window(fitted) == (20.0, 30.0) and notes == []


def test_cut_inside_the_window_shortens_it_and_after_it_changes_nothing() -> None:
    effects = VideoEffects(redacts=(Redact(Rect(0, 0, 5, 5), show_from=10.0, show_to=30.0),))
    old = _project(effects)
    inside = retime(old, RemoveRange(15, 25).apply(old))[0]
    assert _window(inside, "redact") == (10.0, 20.0)
    after = retime(old, RemoveRange(40, 50).apply(old))[0]
    assert _window(after, "redact") == (10.0, 30.0)


def test_open_end_stays_open_and_default_effects_are_untouched() -> None:
    effects = VideoEffects(texts=(Text("a", 0, 0, show_from=30.0), Text("b", 0, 0)))
    old = _project(effects)
    fitted, _notes = retime(old, RemoveRange(0, 10).apply(old))
    first, second = fitted.effects.texts
    assert (first.show_from, first.show_to) == (20.0, -1.0)  # конец «до конца ролика» остался
    assert second == Text("b", 0, 0)


def test_window_removed_entirely_is_reported() -> None:
    effects = VideoEffects(texts=(Text("Скрытый", 0, 0, show_from=12.0, show_to=18.0),))
    old = _project(effects)
    fitted, notes = retime(old, RemoveRange(10, 20).apply(old))
    assert [n.kind for n in notes].count("collapsed") == 1 and notes[0].label == "Скрытый"
    start, stop = _window(fitted)
    assert stop - start < 0.04


def test_window_follows_its_block_when_blocks_are_moved() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=25.0, show_to=35.0),))
    old = VideoProject(_project().split_at(20).split_at(40).clips, effects=effects)
    # блок 20-40 ставим в конец: текст был на 5-15 секундах этого блока, теперь он в 40-60
    fitted, notes = retime(old, MoveBlock(1, 2).apply(old))
    assert _window(fitted) == (45.0, 55.0) and notes == []


def test_stretching_a_block_edge_keeps_the_window_on_the_same_picture() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=40.0, show_to=50.0),))
    old = VideoProject(_project().split_at(20).clips, effects=effects)
    # конец первого блока растянули с 20 до 30: второй блок сдвинулся на 10 секунд вправо
    fitted, _ = retime(old, TrimBlock(0, 0.0, 30.0).apply(old))
    assert _window(fitted) == (50.0, 60.0)  # блок 2 начался на 10 с позже, окно ушло за ним


def test_removing_a_block_with_the_window_end_clamps_and_warns() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=70.0, show_to=100.0),))
    old = _project(effects, clips=2)  # по 60 секунд
    fitted, notes = retime(old, RemoveBlock(1).apply(old))  # итог стал 60 с
    assert [n.kind for n in notes].count("clamped") == 1
    assert _window(fitted)[0] == 60.0


def test_session_applies_the_retime_in_one_history_step_and_reports() -> None:
    effects = VideoEffects(texts=(Text("t", 0, 0, show_from=30.0, show_to=40.0),))
    session = VideoSession(_project(effects))
    seen: list[list[object]] = []
    session.timeNotes.connect(seen.append)
    session.cut(RemoveRange(10, 20))
    assert session.project.effects.texts[0].show_from == 20.0
    assert seen == []
    session.undo()  # отмена возвращает и время показа
    assert session.project.effects.texts[0].show_from == 30.0
    session.cut(RemoveRange(28, 45))
    assert len(seen) == 1 and seen[0][0].kind == "collapsed"  # type: ignore[attr-defined]


@pytest.mark.parametrize(("a", "b"), [(0.0, -1.0), (1.0, -1.0), (1.0, 3.0), (0.0, 3.0)])
def test_untouched_windows_survive(a: float, b: float) -> None:
    text = Text("x", 0, 0, show_from=a, show_to=b)
    old = _project(VideoEffects(texts=(text,)))
    fitted, _ = retime(old, old)
    assert fitted.effects.texts[0] == text


# --- позиция воспроизведения после правки ----------------------------------------------------


def test_position_stays_on_the_same_picture() -> None:
    old = _project().split_at(20).split_at(40)
    moved = MoveBlock(1, 2).apply(old)  # блок 20-40 теперь последний
    assert map_position(old, moved, 25.0) == 45.0  # тот же кадр файла, но в новом месте
    assert map_position(old, moved, 5.0) == 5.0


def test_position_of_a_removed_block_stays_inside_the_new_length() -> None:
    old = _project().split_at(20).split_at(40)
    cut = RemoveBlock(2).apply(old)  # итог теперь 40 с
    assert map_position(old, cut, 50.0) <= cut.duration
