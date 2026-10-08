from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from fakes import FakeEndFileEvent, FakeMpv
from quickedit.player.player import Player
from quickedit.player.resume import ResumeState
from quickedit.services.settings import PlayerPrefs

TRACKS = [
    {"id": 1, "type": "audio", "lang": "eng"},
    {"id": 2, "type": "audio", "lang": "rus"},
    {"id": 1, "type": "sub", "lang": "eng"},
    {"id": 2, "type": "sub", "lang": "rus"},
]


def _player() -> tuple[Player, FakeMpv]:
    fake = FakeMpv()
    fake.track_list = TRACKS
    return Player(fake), fake


def test_load_without_resume_starts_from_beginning() -> None:
    player, fake = _player()
    fake.pause = True
    player.load(Path("movie.mkv"))
    assert fake.loaded == [("movie.mkv", {})]
    assert fake.pause is False


def test_load_applies_resume_state() -> None:
    player, fake = _player()
    state = ResumeState(
        position=12.5,
        volume=70,
        aid=2,
        sid=0,
        secondary_sid=1,
        sub_delay=0.5,
        secondary_sub_delay=-0.2,
    )
    player.load(Path("movie.mkv"), state)
    _, options = fake.loaded[0]
    assert options == {
        "start": "12.500",
        "aid": 2,
        "sid": "no",
        "secondary-sid": 1,
        "sub-delay": 0.5,
        "secondary-sub-delay": -0.2,
    }
    assert fake.volume == 70


def test_cycle_subtitles_goes_through_off() -> None:
    player, fake = _player()
    player.cycle_sub()
    assert fake.sid == 1
    fake.sid = 2
    player.cycle_sub()
    assert fake.sid == "no"


def test_cycle_audio_wraps_and_second_subtitle_is_independent() -> None:
    player, fake = _player()
    fake.aid = 2
    player.cycle_audio()
    assert fake.aid == 1
    fake.sid = 1
    player.cycle_sub2()
    assert fake.secondary_sid == 2  # та же дорожка, что у основных, не предлагается
    assert fake.sid == 1


def test_cycling_skips_track_used_by_other_line() -> None:
    player, fake = _player()
    fake.sid = 1
    player.cycle_sub2()
    assert fake.secondary_sid == 2  # дорожка 1 занята основными субтитрами
    fake.secondary_sid = 2
    player.cycle_sub2()
    assert fake.secondary_sid == "no"
    fake.secondary_sid = 2
    player.cycle_sub()
    assert fake.sid == "no"  # у основных свободна только дорожка 1, после неё — выкл.


def test_subtitle_shift_uses_100ms_steps_per_track() -> None:
    player, fake = _player()
    player.shift_sub(1)
    player.shift_sub(1)
    player.shift_sub(1)
    player.shift_sub2(-1)
    assert fake.sub_delay == pytest.approx(0.3)
    assert fake.secondary_sub_delay == pytest.approx(-0.1)


def test_volume_is_clamped() -> None:
    player, fake = _player()
    player.add_volume(500)
    assert fake.volume == 130
    player.set_volume(-5)
    assert fake.volume == 0


def test_seek_and_pause() -> None:
    player, fake = _player()
    player.seek(-5)
    player.seek_to(-3)
    assert fake.seeks == [(-5, "relative", "keyframes"), (0.0, "absolute", "keyframes")]
    player.toggle_pause()
    assert fake.pause is True


def test_state_maps_disabled_tracks_to_zero() -> None:
    player, fake = _player()
    fake.aid, fake.sid, fake.secondary_sid = 2, "no", False
    fake.time_pos = 33.0
    state = player.state()
    assert (state.aid, state.sid, state.secondary_sid) == (2, 0, 0)
    assert state.position == 33.0


def test_add_subtitle_and_apply_prefs() -> None:
    player, fake = _player()
    player.add_subtitle(Path("movie.srt"))
    assert fake.subtitles == ["movie.srt"]
    player.apply_prefs(PlayerPrefs("rus", "eng", 40, 10))
    assert (fake.sub_font_size, fake.sub_margin_y, fake.alang, fake.slang) == (40, 10, "rus", "eng")


def test_property_observers_become_signals(qtbot: QtBot) -> None:
    player, fake = _player()
    with qtbot.waitSignal(player.positionChanged) as position:
        fake.fire("time-pos", 4.5)
    assert position.args == [4.5]
    with qtbot.waitSignal(player.pausedChanged) as paused:
        fake.fire("pause", True)
    assert paused.args == [True]
    with qtbot.waitSignal(player.tracksChanged):
        fake.fire("track-list", TRACKS)
    with qtbot.waitSignal(player.ended):
        fake.fire("eof-reached", True)


def test_none_values_do_not_emit(qtbot: QtBot) -> None:
    player, fake = _player()
    with qtbot.assertNotEmitted(player.positionChanged):
        fake.fire("time-pos", None)
    with qtbot.assertNotEmitted(player.ended):
        fake.fire("eof-reached", False)


def test_playback_error_is_reported(qtbot: QtBot) -> None:
    player, fake = _player()
    with qtbot.waitSignal(player.errorOccurred):
        fake.event_handlers[0](FakeEndFileEvent(b"error"))
    with qtbot.assertNotEmitted(player.errorOccurred):
        fake.event_handlers[0](FakeEndFileEvent(b"eof"))


def test_shutdown_is_idempotent() -> None:
    player, fake = _player()
    player.shutdown()
    player.stop()  # после остановки команды не отправляются
    player.shutdown()
    assert fake.terminated
    assert fake.commands == []
