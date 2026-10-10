from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from chopchop.core.subtitle_style import SubtitleStyle
from chopchop.player.player import Player
from chopchop.player.resume import ResumeState
from chopchop.services.settings import PlayerPrefs
from fakes import FakeEndFileEvent, FakeMpv, FakeOldMpv

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
    fake.fire("sid", 2)  # наблюдатель mpv сообщает о смене
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
    player.apply_prefs(
        PlayerPrefs("rus", "eng", 40, 10, style=SubtitleStyle(font_size=40, margin_y=10))
    )
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


def test_old_mpv_without_secondary_sub_delay_still_works() -> None:
    fake = FakeOldMpv()
    fake.track_list = TRACKS
    player = Player(fake)
    assert not player.supports_secondary_delay
    player.shift_sub2(1)  # игнорируется, не падает
    assert player.state().secondary_sub_delay == 0.0
    player.load(Path("movie.mkv"), ResumeState(position=10.0, secondary_sub_delay=0.5))
    _, options = fake.loaded[0]
    assert "secondary-sub-delay" not in options
    assert options["sub-delay"] == 0.0
    player.shift_sub(1)  # сдвиг основных субтитров работает как обычно
    assert fake.sub_delay == pytest.approx(0.1)


def test_loop_range_and_file_loaded_signal(qtbot: QtBot) -> None:
    player, fake = _player()
    player.set_loop(2.5, 8.0)
    assert (fake.ab_loop_a, fake.ab_loop_b) == (2.5, 8.0)
    player.set_loop(None, None)
    assert (fake.ab_loop_a, fake.ab_loop_b) == ("no", "no")
    with qtbot.waitSignal(player.fileLoaded):
        fake.event_handlers[1](object())


def test_restore_video_does_nothing_without_a_file() -> None:
    player, fake = _player()
    player.restore_video()
    assert fake.loaded == []
    assert fake.seeks == []


def test_restore_video_redraws_when_output_is_alive() -> None:
    player, fake = _player()
    player.load(Path("movie.mkv"))
    fake.loaded.clear()
    fake.time_pos = 4.0
    player.restore_video()
    assert fake.seeks == [(0, "relative", "exact")]
    assert fake.loaded == []


def test_restore_video_reloads_file_when_output_was_lost() -> None:
    player, fake = _player()
    player.load(Path("movie.mkv"))
    fake.loaded.clear()
    fake.vo_configured = False
    fake.time_pos = 7.5
    fake.pause = True
    player.restore_video()
    assert fake.loaded == [("movie.mkv", {"start": "7.500", "pause": "yes"})]
    fake.loaded.clear()
    fake.pause = False
    player.restore_video()
    assert fake.loaded[0][1]["pause"] == "no"


def test_restore_video_before_playback_started_reloads_from_start() -> None:
    player, fake = _player()
    player.load(Path("movie.mkv"))  # контекста рендера ещё не было, позиции нет
    fake.loaded.clear()
    fake.time_pos = None
    player.restore_video()
    assert fake.loaded == [("movie.mkv", {"start": "0.000", "pause": "no"})]


def test_video_filter_is_set_and_cleared() -> None:
    player, fake = _player()
    assert player.set_video_filter("[vid1]hue=s=0[vo]")
    assert ("vf", "set", "lavfi=[[vid1]hue=s=0[vo]]") in fake.commands
    assert player.set_video_filter(None)
    assert fake.commands[-1] == ("vf", "clear", "")


def test_filter_switches_zero_copy_decoding_to_copy_mode_once() -> None:
    player, fake = _player()
    player.load(Path("movie.mkv"))
    fake.loaded.clear()
    fake.hwdec_current = "nvdec"  # кадры остаются в памяти видеокарты
    fake.time_pos = 6.0
    fake.pause = True
    player.set_video_filter("[vid1]hue=s=0[vo]")
    assert fake.hwdec == "auto-copy-safe"
    assert fake.loaded == [("movie.mkv", {"start": "6.000", "pause": "yes"})]
    fake.loaded.clear()
    player.set_video_filter("[vid1]eq=contrast=1.2[vo]")  # второй раз без перезапуска
    assert fake.loaded == []


def test_filter_does_not_reload_when_decoding_is_already_in_software_or_copy_mode() -> None:
    for current in ("no", "d3d11va-copy", ""):
        player, fake = _player()
        player.load(Path("movie.mkv"))
        fake.loaded.clear()
        fake.hwdec_current = current
        fake.time_pos = 3.0
        player.set_video_filter("[vid1]hue=s=0[vo]")
        assert fake.loaded == []
        assert fake.hwdec == "auto-copy-safe"


def test_changing_decoding_mode_restarts_the_decoder_at_the_same_place() -> None:
    player, fake = _player()
    player.load(Path("movie.mkv"))
    fake.loaded.clear()
    fake.hwdec = "auto-safe"
    fake.time_pos = 4812.0
    fake.pause = False
    player.apply_prefs(PlayerPrefs(hwdec="no"))
    assert fake.hwdec == "no"
    assert fake.loaded == [("movie.mkv", {"start": "4812.000", "pause": "no"})]
    fake.loaded.clear()
    player.apply_prefs(PlayerPrefs(hwdec="no"))  # то же значение: ничего не перезапускается
    assert fake.loaded == []


def test_filter_keeps_the_users_decoding_choice() -> None:
    player, fake = _player()
    fake.hwdec = "no"
    player.set_video_filter("[vid1]hue=s=0[vo]")
    assert fake.hwdec == "no"  # программное декодирование не подменяется
