"""Плавающие панели, уведомления, полоса экспорта, анимации и страница видео."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEasingCurve, QPoint, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from chopchop.services.app_settings import AppSettings
from chopchop.ui import anim
from chopchop.ui.drop_zone import DropZone
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import current, tokens
from chopchop.ui.toast import Toast
from chopchop.ui.video_page import MINI_LINE, VideoPage
from fakes import FakeMpv, FakeMpvWidget


@pytest.fixture(autouse=True)
def animations_off() -> Iterator[None]:
    anim.set_enabled(False)
    yield
    anim.set_enabled(True)


# --- анимации ----------------------------------------------------------------------------------


def test_animation_switch_makes_changes_instant(qtbot: QtBot) -> None:
    panel = FloatingPanel()
    qtbot.addWidget(panel)
    panel.resize(100, 50)
    panel.show()
    panel.disappear()
    assert not panel.isVisible() and panel.opacity == 0.0  # без анимации сразу
    panel.appear()
    assert panel.isVisible() and panel.opacity == 1.0
    values: list[float] = []
    anim.tween(0, 10, 150, values.append)
    assert values == [10.0]
    assert anim.duration(150) == 0
    anim.set_enabled(True)
    assert anim.duration(150) == 150
    anim.set_enabled(False)


def test_animations_run_with_ease_out_when_enabled(qtbot: QtBot) -> None:
    anim.set_enabled(True)
    panel = FloatingPanel()
    qtbot.addWidget(panel)
    panel.resize(100, 50)
    panel.show()
    panel.disappear()
    assert panel.isVisible()  # ещё исчезает
    qtbot.waitUntil(lambda: not panel.isVisible(), timeout=2000)
    assert anim.ease_out().type() == QEasingCurve.Type.OutCubic
    assert tokens.PANEL_MS == 150 and tokens.HOVER_MS == 100


# --- уведомления и полоса экспорта -------------------------------------------------------------


def test_toast_shows_message_with_action(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 500)
    host.show()
    toast = Toast(host)
    called: list[bool] = []
    toast.show_message(
        "Сохранено: a.jpg", "success", "Показать в папке", lambda: called.append(True)
    )
    assert toast.isVisible() and toast.message() == "Сохранено: a.jpg"
    assert toast.y() + toast.height() <= host.height()
    assert abs(toast.geometry().center().x() - host.width() // 2) <= 2  # по центру внизу
    toast._action.click()
    assert called == [True] and not toast.isVisible()


def test_toast_without_action_hides_button_and_replaces_text(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    host.show()
    toast = Toast(host)
    toast.show_message("Ошибка", "error")
    assert toast._action.isHidden()
    toast.show_message("Другое", "info")
    assert toast.message() == "Другое"
    toast._close.click()
    assert not toast.isVisible()


def test_toast_hides_by_itself(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    host.show()
    toast = Toast(host)
    toast._timer.setInterval(30)
    toast.show_message("Скоро исчезну", "info")
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=2000)


def test_export_strip_progress_and_cancel(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    strip = ExportStrip(host)
    host.show()
    assert strip.isHidden()
    strip.start("Экспорт…")
    assert not strip.isHidden() and strip.value() == 0
    strip.set_fraction(0.42)
    assert strip.value() == 42
    asked: list[bool] = []
    strip.cancelRequested.connect(lambda: asked.append(True))
    strip._cancel.click()
    assert asked == [True]
    strip.cancelling()
    assert not strip._cancel.isEnabled()
    strip.finish()
    assert strip.isHidden()
    strip.start("Сохранение…", indeterminate=True)
    assert strip._bar.maximum() == 0
    strip.set_fraction(0.5)
    assert strip._bar.maximum() == 100


# --- стартовый экран ---------------------------------------------------------------------------


def test_drop_zone_highlights_while_dragging_and_draws_illustration(qtbot: QtBot) -> None:
    zone = DropZone()
    qtbot.addWidget(zone)
    zone.resize(900, 700)
    zone.show()
    assert not zone.dragging
    image = zone._art.grab().toImage()
    palette = current.palette()
    colors = {
        image.pixelColor(x, y).name()
        for x in range(0, image.width(), 4)
        for y in range(0, image.height(), 4)
    }
    assert QColor(palette.accent).name() in colors  # солнце и кнопка воспроизведения
    assert QColor(palette.success).name() in colors  # холмы
    zone._dragging = True
    zone.update()
    assert zone.dragging
    zone._dragging = False


def test_drop_zone_lists_recent_files(qtbot: QtBot) -> None:
    zone = DropZone()
    qtbot.addWidget(zone)
    chosen: list[Path] = []
    zone.fileChosen.connect(chosen.append)
    zone.set_recent([Path("a.jpg"), Path("b.mp4")])
    assert zone._recent.count() == 2 and not zone._recent.isHidden()
    zone._recent.itemClicked.emit(zone._recent.item(1))
    assert chosen == [Path("b.mp4")]
    zone.set_recent([])
    assert zone._recent.isHidden()


# --- страница видео ----------------------------------------------------------------------------


class _Module:
    """Подмена модуля mpv: нужен только конструктору виджета, которого здесь нет."""

    MpvGlGetProcAddressFn = staticmethod(lambda function: function)


def _page(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, **settings: object
) -> tuple[VideoPage, FakeMpv]:
    monkeypatch.setattr("chopchop.ui.video_page.MpvWidget", FakeMpvWidget)
    monkeypatch.setattr("chopchop.ui.video_page.find_ffmpeg", lambda: None)
    app = AppSettings(None)
    for key, value in settings.items():
        app.set(key.replace("__", "."), value)
    mpv = FakeMpv()
    page = VideoPage(_Module(), mpv, settings=app)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    page.resize(1000, 600)
    page.show()
    return page, mpv


def test_panels_fill_the_window_and_sit_at_the_edges(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    assert page.controls.height() == 64
    visual_bottom = page.controls.geometry().bottom() + 1 - page.controls.reserve
    assert page.height() - visual_bottom == tokens.SPACE_4  # отступ от нижнего края окна 16 px
    assert page.top.geometry().top() == tokens.SPACE_4
    assert page.controls.width() == page.width() - 2 * tokens.SPACE_4
    assert page.video.geometry() == page.rect()


def test_fullscreen_panel_is_compact_pill_with_bigger_bottom_gap(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    page.resize(1600, 900)
    page.set_fullscreen(True)
    controls = page.controls
    assert controls.compact and controls.height() == 44
    assert controls.width() == 720
    assert abs(controls.geometry().center().x() - page.width() // 2) <= 1
    gap = page.height() - (controls.geometry().bottom() + 1 - controls.reserve)
    assert abs(gap - tokens.SPACE_6) <= 1  # отступ снизу 24 px
    page.set_fullscreen(False)
    assert not controls.compact and controls.height() == 64


def test_fullscreen_panel_size_follows_the_setting(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch, playback__fs_panel="normal")
    page.set_fullscreen(True)
    assert not page.controls.compact and page.controls.height() == 64


def test_panels_hide_when_the_mouse_is_still_and_return_on_move(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, mpv = _page(qtbot, monkeypatch)
    mpv.pause = False
    page.wake()
    assert page.controls.isVisible() and page.top.isVisible()
    page._hide_idle()
    assert not page.controls.isVisible() and not page.top.isVisible()
    page.video.mouseMoved.emit()  # движение мыши возвращает панели
    assert page.controls.isVisible() and page.top.isVisible()


def test_panels_stay_while_paused_or_drawer_open_or_pointer_inside(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, mpv = _page(qtbot, monkeypatch)
    mpv.pause = True
    page._hide_idle()
    assert page.controls.isVisible()  # пауза: панель остаётся
    mpv.pause = False
    page.toggle_tracks()
    assert page.tracks.isVisible()
    page._hide_idle()
    assert page.controls.isVisible()  # боковая панель открыта
    page.toggle_tracks()
    assert not page.tracks.isVisible()
    page.controls.is_pointer_inside = lambda: True  # type: ignore[method-assign]
    page._hide_idle()
    assert page.controls.isVisible()  # курсор над панелью


def test_hide_delay_comes_from_settings(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _mpv = _page(qtbot, monkeypatch, playback__hide_delay=4.0)
    assert page.hide_delay_ms() == 4000
    page.wake()
    assert page._hide_timer.interval() == 4000


def test_thin_progress_line_remains_in_fullscreen_when_panel_is_hidden(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, mpv = _page(qtbot, monkeypatch)
    mpv.pause = False
    page.set_fullscreen(True)
    page._hide_idle()
    assert not page.controls.isVisible()
    assert page.mini.isVisible() and page.mini.height() == MINI_LINE
    assert page.mini.y() == page.height() - MINI_LINE
    page.wake()
    assert not page.mini.isVisible()  # панель вернулась, линия не нужна


def test_progress_line_can_be_switched_off(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, mpv = _page(qtbot, monkeypatch, playback__fs_progress_line=False)
    mpv.pause = False
    page.set_fullscreen(True)
    page._hide_idle()
    assert not page.mini.isVisible()


def test_mini_progress_follows_playback(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, mpv = _page(qtbot, monkeypatch)
    mpv.fire("duration", 100.0)
    qtbot.waitUntil(lambda: page._duration == 100.0, timeout=2000)
    mpv.fire("time-pos", 25.0)
    qtbot.waitUntil(lambda: page.mini._fraction == 0.25, timeout=2000)


def test_title_and_editor_mode(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    page.set_title("очень_длинное_название_файла_для_проверки_сокращения.mp4")
    assert page.top.text().startswith("очень_длинное")
    page.set_editor_mode(True)
    assert not page.top.isVisible()
    page.wake()
    assert not page.top.isVisible()  # в редакторе верхней панели нет


def test_edit_button_and_fullscreen_button_emit_signals(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    asked: list[str] = []
    page.editRequested.connect(lambda: asked.append("edit"))
    page.fullscreenRequested.connect(lambda: asked.append("full"))
    page.top._edit.click()
    page.controls._full.click()
    assert asked == ["edit", "full"]


def test_theme_switch_recolours_panels(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    before = page.controls._play.icon().pixmap(QSize(32, 32), 1.0).toImage().pixelColor(8, 8).name()
    from chopchop.ui.theme import current as active
    from chopchop.ui.theme.tokens import DARK

    previous = active.palette()
    try:
        active.set_palette(DARK)
        page.refresh_theme()
        after = (
            page.controls._play.icon().pixmap(QSize(32, 32), 1.0).toImage().pixelColor(8, 8).name()
        )
        assert before != after
    finally:
        active.set_palette(previous)
        page.refresh_theme()


def test_hover_bubble_shows_time_above_the_line(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    page._on_progress_hover(75.0, QPoint(300, 0))
    assert page.bubble.isVisible()
    assert page.bubble._time.text() == "1:15"
    assert page.bubble.geometry().bottom() <= page.controls.geometry().top() + 1
