"""Проверка с настоящим libmpv без окна и звука; пропускается, если библиотеки нет."""

import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from chopchop.player.libmpv import find_libmpv, load_mpv_module
from chopchop.player.player import Player
from chopchop.player.resume import ResumeState

pytestmark = pytest.mark.skipif(find_libmpv() is None, reason="libmpv не установлена")

SRT = "1\n00:00:00,000 --> 00:00:05,000\nПривет\n"


@pytest.fixture
def player(qtbot: QtBot) -> Iterator[Player]:
    module = load_mpv_module()
    mpv = module.MPV(
        vo="null",
        ao="null",
        config=False,
        load_scripts=False,
        terminal=False,
        ytdl=False,
        keep_open=True,
    )
    instance = Player(mpv)
    yield instance
    instance.shutdown()


def _wav(path: Path, seconds: int = 8) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 8000 * seconds)
    return path


def test_load_resumes_from_saved_position(qtbot: QtBot, tmp_path: Path, player: Player) -> None:
    media = _wav(tmp_path / "a.wav")
    player.load(media, ResumeState(position=3.0))
    qtbot.waitUntil(lambda: player.duration is not None and player.position >= 3.0, timeout=10000)
    assert player.duration == pytest.approx(8.0, abs=0.2)


def test_two_subtitle_tracks(qtbot: QtBot, tmp_path: Path, player: Player) -> None:
    media = _wav(tmp_path / "a.wav")
    first = tmp_path / "first.srt"
    second = tmp_path / "second.srt"
    first.write_text(SRT, encoding="utf-8")
    second.write_text(SRT, encoding="utf-8")
    player.load(media)
    qtbot.waitUntil(lambda: player.duration is not None, timeout=10000)

    player.add_subtitle(first)
    player.add_subtitle(second)
    qtbot.waitUntil(lambda: len([t for t in player.tracks() if t.kind == "sub"]) == 2, timeout=5000)

    subs = [t for t in player.tracks() if t.kind == "sub"]
    assert all(t.external for t in subs)
    player.set_sub(subs[0].id)
    player.set_sub2(subs[1].id)
    qtbot.waitUntil(lambda: player.sub2_id() == subs[1].id, timeout=5000)
    assert player.sub_id() == subs[0].id

    player.shift_sub(2)
    player.shift_sub2(-1)
    state = player.state()
    assert state.sub_delay == pytest.approx(0.2)
    if player.supports_secondary_delay:  # в старых mpv этого свойства нет
        assert state.secondary_sub_delay == pytest.approx(-0.1)

    player.set_sub2(None)
    qtbot.waitUntil(lambda: player.sub2_id() is None, timeout=5000)


def test_missing_file_reports_error(qtbot: QtBot, tmp_path: Path, player: Player) -> None:
    with qtbot.waitSignal(player.errorOccurred, timeout=10000):
        player.load(tmp_path / "missing.mkv")
