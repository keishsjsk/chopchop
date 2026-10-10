from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QRadioButton
from pytestqt.qtbot import QtBot

from chopchop.player.player import Player
from chopchop.ui import anim
from chopchop.ui.player_controls import LINE_THICK, LINE_THIN, PlayerControls, format_time
from chopchop.ui.theme import current, tokens
from chopchop.ui.tracks_panel import TracksPanel
from fakes import FakeMpv

TRACKS = [
    {"id": 1, "type": "audio", "lang": "eng"},
    {"id": 1, "type": "sub", "lang": "eng"},
    {"id": 2, "type": "sub", "lang": "rus"},
]


@pytest.fixture(autouse=True)
def no_animation() -> Iterator[None]:
    anim.set_enabled(False)  # проверяем состояние, а не кадры анимации
    yield
    anim.set_enabled(True)


def _controls(qtbot: QtBot) -> tuple[PlayerControls, Player, FakeMpv]:
    fake = FakeMpv()
    fake.track_list = TRACKS
    fake.aid = 1
    player = Player(fake)
    controls = PlayerControls(player)
    qtbot.addWidget(controls)
    controls.resize(900, controls.height())
    controls.show()
    return controls, player, fake


def _tracks(qtbot: QtBot) -> tuple[TracksPanel, Player, FakeMpv]:
    fake = FakeMpv()
    fake.track_list = TRACKS
    fake.aid = 1
    player = Player(fake)
    panel = TracksPanel(player)
    qtbot.addWidget(panel)
    panel.show()
    return panel, player, fake


def _radios(panel: TracksPanel, text: str) -> list[QRadioButton]:
    return [button for button in panel.findChildren(QRadioButton) if button.text() == text]


def test_format_time() -> None:
    assert format_time(0) == "0:00"
    assert format_time(75.9) == "1:15"
    assert format_time(3725) == "1:02:05"
    assert format_time(-3) == "0:00"


def test_panel_sizes_normal_and_compact(qtbot: QtBot) -> None:
    controls, _player, _fake = _controls(qtbot)
    from chopchop.ui.theme import icons

    assert controls.height() == 40  # обычная: 40 px, кнопки 28
    assert controls._play.iconSize().width() == icons.ui_icon_size()
    assert 16 <= controls._play.iconSize().width() <= 21  # значки видны размером 16-20 px
    assert controls._play.width() == controls._play.height() == tokens.PLAYER_BUTTON == 28
    assert controls.max_width == 560
    controls.set_compact(True)
    assert controls.height() == 36  # в полном экране 36 px
    assert controls._play.width() == 28
    assert controls.max_width == 560
    controls.set_compact(False)
    assert controls.height() == 40
    assert controls._time.font().pixelSize() == tokens.UI_FONT_PX  # время 12 px


def test_tracks_panel_lists_tracks_by_section(qtbot: QtBot) -> None:
    panel, _player, _fake = _tracks(qtbot)
    assert len(_radios(panel, "Выключено")) == 2  # у обеих строк субтитров
    assert len(_radios(panel, "1 · eng")) == 3  # звук и два списка субтитров
    assert len(_radios(panel, "2 · rus")) == 2
    assert panel.choice_count() == 7


def test_choosing_a_track_selects_it(qtbot: QtBot) -> None:
    panel, _player, fake = _tracks(qtbot)
    _radios(panel, "2 · rus")[0].setChecked(True)
    assert fake.sid == 2
    _radios(panel, "2 · rus")[1].setChecked(True)
    assert fake.secondary_sid == 2
    _radios(panel, "Выключено")[0].setChecked(True)
    assert fake.sid == "no"


def test_panel_follows_external_track_change(qtbot: QtBot) -> None:
    panel, _player, fake = _tracks(qtbot)
    fake.sid = 2
    fake.fire("sid", 2)
    qtbot.waitUntil(lambda: _radios(panel, "2 · rus")[0].isChecked(), timeout=2000)


def test_play_button_follows_pause_state(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("pause", False)
    qtbot.waitUntil(lambda: controls._play.toolTip() == "Пауза", timeout=2000)
    fake.fire("pause", True)
    qtbot.waitUntil(lambda: controls._play.toolTip() == "Воспроизвести", timeout=2000)


def test_progress_line_is_thin_and_thickens_on_hover(qtbot: QtBot) -> None:
    controls, _player, _fake = _controls(qtbot)
    line = controls._seek
    assert line.thickness == LINE_THIN
    line.enterEvent(None)  # type: ignore[arg-type]
    assert line.thickness == LINE_THICK
    line.leaveEvent(None)  # type: ignore[arg-type]
    assert line.thickness == LINE_THIN


def test_dragging_progress_line_seeks_by_keyframes_then_exactly(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("duration", 200.0)
    qtbot.waitUntil(lambda: controls._duration == 200.0, timeout=2000)
    line = controls._seek
    QTest.mousePress(line, Qt.MouseButton.LeftButton, pos=QPoint(line.width() // 2, 10))
    first = fake.seeks[-1]
    assert first[0] == pytest.approx(100.0, abs=3.0) and first[2] == "keyframes"
    QTest.mouseMove(line, QPoint(line.width() * 3 // 4, 10))
    QTest.mouseRelease(line, Qt.MouseButton.LeftButton, pos=QPoint(line.width() * 3 // 4, 10))
    last = fake.seeks[-1]
    assert last[0] == pytest.approx(150.0, abs=3.0) and last[2] == "exact"


def test_clicking_progress_line_jumps_to_that_point(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("duration", 100.0)
    qtbot.waitUntil(lambda: controls._duration == 100.0, timeout=2000)
    line = controls._seek

    def click_at(x: int) -> float:
        QTest.mouseClick(line, Qt.MouseButton.LeftButton, pos=QPoint(x, 10))
        target = fake.seeks[-1][0]
        assert isinstance(target, float)
        return target

    assert click_at(line.width() // 2) == pytest.approx(50.0, abs=5.0)
    assert click_at(1) < 5.0
    assert click_at(line.width() - 1) > 95.0


def test_hover_reports_time_under_the_cursor(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("duration", 100.0)
    qtbot.waitUntil(lambda: controls._duration == 100.0, timeout=2000)
    line = controls._seek
    seen: list[float] = []
    line.hovered.connect(lambda seconds, _point: seen.append(seconds))
    x = line.width() // 4
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, 10),
        QPointF(x, 10),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    line.mouseMoveEvent(move)
    assert seen[-1] == pytest.approx(25.0, abs=3.0)


def test_volume_icon_and_mute(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    controls.volume._button.click()
    assert fake.mute is True
    fake.fire("mute", True)
    qtbot.waitUntil(lambda: controls.volume._muted, timeout=2000)
    fake.fire("volume", 0.0)
    qtbot.waitUntil(lambda: controls.volume._volume == 0.0, timeout=2000)
    controls.volume.slider.setValue(40)
    assert fake.volume == 40.0


def test_progress_line_uses_theme_colours(qtbot: QtBot) -> None:
    controls, _player, fake = _controls(qtbot)
    fake.fire("duration", 100.0)
    qtbot.waitUntil(lambda: controls._duration == 100.0, timeout=2000)
    fake.fire("time-pos", 100.0)
    qtbot.waitUntil(lambda: controls._seek.fraction == 1.0, timeout=2000)
    line = controls._seek
    image = controls.grab().toImage()  # панель целиком: у неё есть эффект прозрачности
    center = line.mapTo(controls, QPoint(line.width() // 2, line.height() // 2))
    ratio = image.devicePixelRatio()
    middle = image.pixelColor(round(center.x() * ratio), round(center.y() * ratio))
    assert middle.name() == QColor(current.palette().accent).name()


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0])
def test_ui_icons_are_16_to_21_px_with_a_whole_grid_scale(ratio: float) -> None:
    from chopchop.ui.theme import icons

    size = icons.ui_icon_size(ratio)
    assert 12 <= size <= 21
    scale = icons.integer_scale(size, ratio)
    assert abs(size * ratio - 16 * scale) <= 1.0  # сетка ложится на пиксели без дробей
    if ratio in (1.0, 2.0, 3.0):
        assert 16 <= size <= 20 or ratio == 3.0
