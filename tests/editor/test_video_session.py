from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from quickedit.core.document import AudioInfo, MediaInfo
from quickedit.core.geometry import Rect
from quickedit.core.operations import Adjust, Redact, Text
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


def test_crop_is_clamped_and_full_frame_means_no_crop() -> None:
    session = _session()
    session.set_crop(Rect(-20, -20, 400, 200))  # вылезает за кадр 640x360
    assert session.project.effects.crop == Rect(0, 0, 380, 180)
    session.set_crop(Rect(0, 0, 640, 360))
    assert session.project.effects.crop is None
    session.set_crop(Rect(700, 700, 10, 10))  # целиком за кадром
    assert session.project.effects.crop is None


def test_redacts_texts_color_and_filter_accumulate_with_undo() -> None:
    session = _session()
    session.add_redact(Redact(Rect(0, 0, 50, 50)))
    session.add_redact(Redact(Rect(60, 0, 50, 50), "blur", 8.0))
    session.add_text(Text("Привет", 10, 10))
    session.set_adjust(Adjust(contrast=1.2))
    session.set_filter("sepia")
    effects = session.project.effects
    assert len(effects.redacts) == 2
    assert [t.text for t in effects.texts] == ["Привет"]
    assert effects.adjust.contrast == 1.2
    assert effects.filter == "sepia"
    assert effects.describe() == ["скрытия: 2", "текст: 1", "цвет", "фильтр"]
    session.undo()
    assert session.project.effects.filter is None
    session.undo()
    assert session.project.effects.adjust.is_identity


def test_rotation_accumulates_and_flips_toggle() -> None:
    session = _session()
    session.rotate(90)
    session.rotate(90)
    session.rotate(270)
    assert session.project.effects.rotation == 90
    session.rotate(270)
    assert session.project.effects.rotation == 0
    session.flip(True)
    assert session.project.effects.flip_h
    session.flip(True)
    assert not session.project.effects.flip_h
    session.flip(False)
    assert session.project.effects.flip_v


def test_clear_effects_keeps_clips_and_audio() -> None:
    session = _session()
    session.set_volume(0.5)
    session.set_filter("blur")
    session.rotate(90)
    session.clear_effects()
    assert session.project.effects.is_default
    assert session.project.audio.volume == 0.5
    assert session.project.reencode_reason() is None
