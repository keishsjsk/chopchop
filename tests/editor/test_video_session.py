from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from quickedit.core.document import AudioInfo, MediaInfo
from quickedit.core.video import Clip, VideoProject
from quickedit.editor.video_session import VideoSession

INFO = MediaInfo(640, 360, 60.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _session() -> VideoSession:
    return VideoSession(VideoProject((Clip(Path("a.mp4"), INFO),)))


def test_trim_undo_redo_and_modified(qtbot: QtBot) -> None:
    session = _session()
    assert not session.modified
    with qtbot.waitSignal(session.changed):
        session.set_trim(0, 10, 30)
    assert session.project.clips[0].start == 10
    assert session.modified
    assert session.can_undo
    session.undo()
    assert not session.modified
    assert not session.project.clips[0].is_trimmed
    session.redo()
    assert session.project.clips[0].stop == 30


def test_identical_change_is_not_recorded(qtbot: QtBot) -> None:
    session = _session()
    session.set_trim(0, 0, 60)  # на весь файл — то же, что и было
    session.set_volume(1.0)
    assert not session.can_undo


def test_clip_editing() -> None:
    session = _session()
    session.add_clip(Clip(Path("b.mp4"), INFO))
    session.move_clip(1, -1)
    assert [c.path.name for c in session.project.clips] == ["b.mp4", "a.mp4"]
    session.remove_clip(0)
    assert [c.path.name for c in session.project.clips] == ["a.mp4"]
    session.remove_clip(0)  # единственный клип остаётся
    assert len(session.project.clips) == 1


def test_audio_changes() -> None:
    session = _session()
    session.set_volume(1.5)
    session.set_mute(True)
    assert session.project.audio.volume == pytest.approx(1.5)
    assert session.project.audio.mute
    session.set_replacement(Path("song.mp3"))
    assert session.project.audio.replacement == Path("song.mp3")
    assert not session.project.audio.mute  # своя дорожка включает звук
    session.set_replacement(None)
    assert session.project.audio.replacement is None


def test_mark_saved(qtbot: QtBot) -> None:
    session = _session()
    session.set_volume(0.5)
    session.mark_saved()
    assert not session.modified
    session.undo()
    assert session.modified
