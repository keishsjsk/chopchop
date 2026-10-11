"""Плашка с названием файла вверху плеера: ширина по тексту, сокращение, вторая строка, события."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot
from test_floating_ui import _page

from chopchop.ui.theme import fonts, tokens
from chopchop.ui.top_bar import MAX_SHARE, TopBar, elide_keep_extension

LONG = "Очень длинное название фильма про путешествие 2024.mkv"


def _metrics() -> QFontMetrics:
    return QFontMetrics(fonts.ui_font(fonts.BODY))


def test_elision_keeps_the_extension_and_the_end_of_the_name(qtbot: QtBot) -> None:
    short = elide_keep_extension(LONG, _metrics(), 300)
    assert "…" in short and short.endswith("2024.mkv")
    assert short.startswith("Очень")
    assert _metrics().horizontalAdvance(short) <= 300
    assert elide_keep_extension("a.mp4", _metrics(), 300) == "a.mp4"  # короткое не трогаем


def test_plate_is_flat_compact_and_left_top(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    page.set_title("кино.mkv")
    plate = page.top
    assert plate.height() <= 32
    assert (plate.x(), plate.y()) == (tokens.SPACE_3, tokens.SPACE_3)  # слева сверху, 12 px
    assert plate.width() < page.width() * 0.4  # короткое имя: плашка узкая, а не на всю ширину
    assert not plate.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert plate.reserve == 0  # без тени


def test_long_name_is_capped_at_forty_percent_of_the_window(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch)
    page.set_title(LONG * 3)
    assert page.top.width() <= int(page.width() * MAX_SHARE)
    assert page.top.displayed_name().endswith(".mkv") and "…" in page.top.displayed_name()
    assert page.top.toolTip() == LONG * 3  # полное имя в подсказке
    page.resize(500, 400)
    assert page.top.width() <= int(500 * MAX_SHARE)


def test_info_line_only_on_hover_or_pause(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, mpv = _page(qtbot, monkeypatch)
    page.set_title("кино.mkv")
    mpv.fire("width", 1920)
    mpv.fire("height", 1080)
    mpv.fire("duration", 6130.0)
    qtbot.waitUntil(lambda: "1:42:10" in page.top.info(), timeout=2000)
    assert page.top.info().startswith("1920×1080 · 1:42:10")
    assert not page.top.info_visible()  # видео играет, мыши нет
    mpv.fire("pause", True)
    assert page.top.info_visible()
    mpv.fire("pause", False)
    assert not page.top.info_visible()
    QApplication.sendEvent(page.top, QEvent(QEvent.Type.Enter))
    page.top._hover = True
    assert page.top.info_visible()
    assert page.top.height() <= 32  # вторая строка не растягивает плашку


def test_info_includes_file_size(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    folder = Path(str(tmp_path))
    video = folder / "v.mkv"
    video.write_bytes(b"x" * (3 * 1024 * 1024))
    page, _mpv = _page(qtbot, monkeypatch)
    page.set_title(video.name, video)
    assert page.top.info().endswith("МБ") or page.top.info().endswith("MB")


def test_double_click_renames_and_right_click_opens_the_menu(qtbot: QtBot) -> None:
    plate = TopBar()
    qtbot.addWidget(plate)
    plate.set_name("кино.mkv")
    plate.resize(200, 32)
    plate.show()
    asked: list[str] = []
    plate.renameRequested.connect(lambda: asked.append("rename"))
    menus: list[QPoint] = []
    plate.menuRequested.connect(menus.append)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(plate, event)
    assert asked == ["rename"]
    context = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(105, 205))
    QApplication.sendEvent(plate, context)
    assert menus == [QPoint(105, 205)]
    assert not hasattr(plate, "_edit")  # значка карандаша нет


def test_plate_hides_and_returns_with_the_other_panels(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _mpv = _page(qtbot, monkeypatch, playback__hide_delay=0.3)
    page.set_title("кино.mkv")
    page.wake()
    assert page.top.isVisible()
    qtbot.waitUntil(lambda: not page.top.isVisible(), timeout=3000)
    page.wake()
    qtbot.waitUntil(lambda: page.top.isVisible(), timeout=2000)
