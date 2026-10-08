from pathlib import Path

import pytest

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.video import (
    AudioSettings,
    Clip,
    ProjectHistory,
    VideoProject,
    incompatibility,
)

AUDIO = AudioInfo("aac", 44100, 2)


def _info(**changes: object) -> MediaInfo:
    base = MediaInfo(1280, 720, 60.0, 25.0, "h264", "yuv420p", 0, AUDIO)
    return MediaInfo(**{**base.__dict__, **changes})


def _clip(name: str = "a.mp4", **changes: object) -> Clip:
    return Clip(Path(name), _info(**changes))


def test_untrimmed_clip_spans_whole_file() -> None:
    clip = _clip()
    assert clip.stop == 60.0
    assert clip.length == 60.0
    assert not clip.is_trimmed


def test_trim_is_clamped_to_file() -> None:
    clip = _clip().with_trim(-5, 500)
    assert (clip.start, clip.stop) == (0.0, 60.0)
    assert not clip.is_trimmed
    narrow = _clip().with_trim(10, 10)  # нулевая длина недопустима
    assert narrow.length == pytest.approx(0.1)
    assert _clip().with_trim(59.99, 70).length == pytest.approx(0.1)  # у самого конца
    assert _clip().with_trim(10, 20).is_trimmed


def test_project_duration_and_clip_editing() -> None:
    project = VideoProject((_clip("a.mp4").with_trim(0, 10), _clip("b.mp4").with_trim(5, 20)))
    assert project.duration == pytest.approx(25.0)
    swapped = project.move_clip(0, 1)
    assert [c.path.name for c in swapped.clips] == ["b.mp4", "a.mp4"]
    assert project.move_clip(0, -1) is project  # за границы не двигается
    removed = project.remove_clip(0)
    assert [c.path.name for c in removed.clips] == ["b.mp4"]
    assert removed.remove_clip(0) is removed  # последний клип остаётся
    added = removed.add_clip(_clip("c.mp4"))
    assert len(added.clips) == 2


def test_audio_settings() -> None:
    assert AudioSettings().is_default
    assert not AudioSettings(volume=1.5).is_default
    assert not AudioSettings(mute=True).is_default
    assert not AudioSettings(replacement=Path("x.mp3")).is_default


def test_incompatibility_reasons() -> None:
    base = _info()
    assert incompatibility(base, _info()) is None
    assert incompatibility(base, _info(video_codec="hevc")) == "codec"
    assert incompatibility(base, _info(width=640)) == "resolution"
    assert incompatibility(base, _info(rotation=90)) == "resolution"
    assert incompatibility(base, _info(fps=30.0)) == "fps"
    assert incompatibility(base, _info(fps=25.005)) is None  # допуск на округление
    assert incompatibility(base, _info(pix_fmt="yuv444p")) == "pixel format"
    assert incompatibility(base, _info(audio=None)) == "audio"
    assert incompatibility(base, _info(audio=AudioInfo("aac", 48000, 2))) == "audio"


def test_history_undo_redo() -> None:
    first = VideoProject((_clip(),))
    history = ProjectHistory(first)
    second = first.with_audio(AudioSettings(volume=1.5))
    assert history.push(second)
    assert history.modified
    assert history.undo()
    assert history.current == first
    assert not history.modified
    assert history.redo()
    assert history.current == second
    assert not history.redo()


def test_history_ignores_identical_state_and_clears_redo() -> None:
    first = VideoProject((_clip(),))
    history = ProjectHistory(first)
    assert not history.push(first)
    history.push(first.with_audio(AudioSettings(mute=True)))
    history.undo()
    history.push(first.with_audio(AudioSettings(volume=0.5)))
    assert not history.can_redo


def test_history_mark_saved() -> None:
    first = VideoProject((_clip(),))
    history = ProjectHistory(first)
    history.push(first.with_audio(AudioSettings(mute=True)))
    history.mark_saved()
    assert not history.modified
    history.undo()
    assert history.modified
