import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from chopchop.player.player import Player
from chopchop.ui.player_controls import PlayerControls, format_time
from fakes import FakeMpv

TRACKS = [
    {"id": 1, "type": "audio", "lang": "eng"},
    {"id": 1, "type": "sub", "lang": "eng"},
    {"id": 2, "type": "sub", "lang": "rus"},
]


def _controls(qtbot: QtBot) -> tuple[PlayerControls, Player, FakeMpv]:
    fake = FakeMpv()
    fake.track_list = TRACKS
    fake.aid = 1
    player = Player(fake)
    controls = PlayerControls(player)
    qtbot.addWidget(controls)
    return controls, player, fake


def _texts(menu_actions: list[QAction]) -> list[str]:
    return [a.text() for a in menu_actions if not a.isSeparator()]


def test_format_time() -> None:
    assert format_time(0) == "0:00"
    assert format_time(75.9) == "1:15"
    assert format_time(3725) == "1:02:05"
    assert format_time(-3) == "0:00"


def test_subtitle_menu_lists_tracks(qtbot: QtBot) -> None:
    controls, _player, _fake = _controls(qtbot)
    texts = _texts(controls._sub_menu.actions())
    assert texts[0] == "Выключено"
    assert texts[1:3] == ["1 · eng", "2 · rus"]
    assert len(texts) == 4  # плюс «Загрузить файл…»
    assert _texts(controls._audio_menu.actions()) == ["1 · eng"]


def test_choosing_menu_item_selects_track(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    controls._sub_menu.actions()[2].trigger()
    assert fake.sid == 2
    controls._sub2_menu.actions()[1].trigger()
    assert fake.secondary_sid == 1
    controls._sub_menu.actions()[0].trigger()
    assert fake.sid == "no"


def test_current_track_is_checked_after_change(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.sid = 2
    fake.fire("sid", 2)
    qtbot.waitUntil(lambda: controls._sub_menu.actions()[2].isChecked(), timeout=2000)


def test_play_button_follows_pause_state(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("pause", False)
    qtbot.waitUntil(lambda: controls._play.text() == "⏸", timeout=2000)
    fake.fire("pause", True)
    qtbot.waitUntil(lambda: controls._play.text() == "▶", timeout=2000)


def test_dragging_seek_slider_seeks(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("duration", 200.0)
    qtbot.waitUntil(lambda: controls._duration == 200.0, timeout=2000)
    controls._seek.sliderMoved.emit(500)
    assert fake.seeks[-1] == (100.0, "absolute", "keyframes")


def test_clicking_seek_slider_jumps_to_that_point(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    controls.resize(900, 50)
    controls.show()
    fake.fire("duration", 100.0)
    qtbot.waitUntil(lambda: controls._duration == 100.0, timeout=2000)
    slider = controls._seek

    def click_at(x: int) -> float:
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, 5))
        target = fake.seeks[-1][0]
        assert isinstance(target, float)
        assert not slider.isSliderDown()
        return target

    assert click_at(slider.width() // 2) == pytest.approx(50.0, abs=5.0)
    assert click_at(2) < 5.0
    assert click_at(slider.width() - 2) > 95.0
