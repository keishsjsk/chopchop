"""Перемотка, громкость и позиция не нагружают интерфейс: ограничитель и асинхронные вызовы."""

import time

from pytestqt.qtbot import QtBot

from chopchop.core.tracks import Track
from chopchop.player.player import POSITION_INTERVAL_MS, SEEK_INTERVAL_MS, Player
from chopchop.player.throttle import Throttle
from fakes import FakeMpv

TRACKS = [
    {"id": 1, "type": "audio", "lang": "eng"},
    {"id": 1, "type": "sub", "lang": "eng"},
]


def _player() -> tuple[Player, FakeMpv]:
    fake = FakeMpv()
    fake.track_list = TRACKS
    return Player(fake), fake


def test_throttle_passes_first_value_at_once_and_keeps_the_last(qtbot: QtBot) -> None:
    got: list[int] = []
    throttle: Throttle[int] = Throttle(40, got.append)
    for value in range(10):
        throttle.push(value)
    assert got == [0]  # первое сразу, остальные ждут
    qtbot.waitUntil(lambda: got == [0, 9], timeout=2000)  # итог доходит, промежуточные нет


def test_throttle_cancel_drops_pending_value(qtbot: QtBot) -> None:
    got: list[int] = []
    throttle: Throttle[int] = Throttle(30, got.append)
    throttle.push(1)
    throttle.push(2)
    throttle.cancel()
    qtbot.wait(120)
    assert got == [1]


def test_throttle_rate_is_bounded(qtbot: QtBot) -> None:
    stamps: list[float] = []
    throttle: Throttle[int] = Throttle(30, lambda _v: stamps.append(time.perf_counter()))
    end = time.perf_counter() + 0.3
    value = 0
    while time.perf_counter() < end:  # поток значений гораздо чаще интервала
        throttle.push(value)
        value += 1
        qtbot.wait(1)
    qtbot.wait(100)
    assert len(stamps) <= 0.3 / 0.025 + 3  # не чаще примерно раза в интервал


def test_dragging_seeks_are_throttled_and_final_exact_seek_goes_at_once(qtbot: QtBot) -> None:
    player, fake = _player()
    for second in range(20):
        player.seek_to(float(second))  # перетаскивание: поток ключевых перемоток
    assert len(fake.seeks) == 1  # одна сразу, остальные ждут своей очереди
    player.seek_to(7.0, exact=True)  # отпустили: точная уходит немедленно, отложенное забыто
    assert fake.seeks[-1] == (7.0, "absolute", "exact")
    count = len(fake.seeks)
    qtbot.wait(SEEK_INTERVAL_MS * 3)
    assert len(fake.seeks) == count  # отложенное значение не перебивает точную перемотку


def test_throttled_seek_delivers_the_last_position(qtbot: QtBot) -> None:
    player, fake = _player()
    for second in (1.0, 2.0, 3.0, 4.0):
        player.seek_to(second)
    qtbot.waitUntil(lambda: fake.seeks[-1][0] == 4.0, timeout=2000)
    assert all(precision == "keyframes" for _a, _r, precision in fake.seeks)


def test_seek_goes_through_the_async_command() -> None:
    """Синхронный seek ждал ядро mpv и держал окно; теперь команда уходит асинхронно."""
    player, fake = _player()
    player.seek(5)
    assert fake.async_commands[-1][0] == "seek"


def test_position_updates_for_the_interface_are_limited(qtbot: QtBot) -> None:
    player, fake = _player()
    seen: list[float] = []
    player.positionChanged.connect(seen.append)
    for step in range(100):  # 100 кадров подряд, как при воспроизведении 60 к/с
        fake.fire("time-pos", step / 60)
    qtbot.wait(POSITION_INTERVAL_MS * 3)
    assert 1 <= len(seen) < 20
    assert seen[-1] == 99 / 60  # последняя позиция доходит всегда


def test_tracks_come_from_observers_without_polling_the_core() -> None:
    player, fake = _player()
    fake.polled.clear()
    fake.fire("track-list", TRACKS)
    fake.fire("aid", 1)
    fake.fire("sid", 1)
    fake.polled.clear()
    assert [t.id for t in player.tracks()] == [1, 1]
    assert player.audio_id() == 1 and player.sub_id() == 1
    assert fake.polled == []  # ядро не опрашивали: во время загрузки файла оно занято


def test_paused_state_comes_from_observer() -> None:
    player, fake = _player()
    fake.fire("pause", True)
    fake.polled.clear()
    assert player.paused is True
    assert fake.polled == []


def test_unknown_track_state_falls_back_to_reading() -> None:
    player, fake = _player()
    fake.sid = 1
    assert player.sub_id() == 1  # наблюдатель ещё не сработал: читаем у mpv


def test_track_dataclass_still_parsed() -> None:
    player, _fake = _player()
    assert all(isinstance(track, Track) for track in player.tracks())
