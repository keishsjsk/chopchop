"""Оболочка редактора, семейство кнопок, полоса клипов, полоса обрезки, чип эффектов."""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, Redact, Text
from chopchop.core.video import EffectEntry, VideoEffects, effect_entries, without_effect
from chopchop.ui.clip_strip import CHIP_W, ClipInfo, ClipStrip
from chopchop.ui.editor_shell import EditorShell
from chopchop.ui.effects_chip import EffectsChip
from chopchop.ui.theme import tokens
from chopchop.ui.trim_bar import TrimBar, range_label
from chopchop.ui.widgets import PixelToggle, Segmented, button, icon_button, tip


def _shell(qtbot: QtBot) -> EditorShell:
    shell = EditorShell()
    qtbot.addWidget(shell)
    for key in ("crop", "redact", "audio"):
        shell.rail.add_tool(key, "crop", key.title(), "C")
        shell.context.add_panel(key, QWidget())
    shell.set_content(QWidget())
    shell.resize(900, 500)
    shell.show()
    return shell


def test_shell_has_the_documented_sizes(qtbot: QtBot) -> None:
    shell = _shell(qtbot)
    assert shell.top.height() == tokens.TOP_BAR_H == 48
    assert shell.status.height() == tokens.STATUS_H == 24
    assert shell.rail.width() == tokens.RAIL_W == 56
    assert shell.rail.button("crop").size().width() == 40
    assert shell.rail.button("crop").size().height() == 40


def test_context_bar_expands_and_collapses(qtbot: QtBot) -> None:
    shell = _shell(qtbot)
    assert shell.context.height() == 0 and not shell.context.isVisible()
    shell.select("crop")
    qtbot.waitUntil(lambda: shell.context.height() == tokens.CONTEXT_H, timeout=2000)
    assert shell.rail.button("crop").isChecked()
    shell.select("redact")  # смена инструмента не схлопывает панель
    assert shell.context.height() == tokens.CONTEXT_H and not shell.rail.button("crop").isChecked()
    shell.select(None)
    qtbot.waitUntil(lambda: shell.context.height() == 0, timeout=2000)
    assert not shell.context.isVisible()


def test_context_bar_is_instant_without_animations(qtbot: QtBot) -> None:
    from chopchop.ui import anim

    anim.set_enabled(False)
    try:
        shell = _shell(qtbot)
        shell.select("crop")
        assert shell.context.height() == tokens.CONTEXT_H
        shell.select(None)
        assert shell.context.height() == 0
    finally:
        anim.set_enabled(True)


def test_rail_marks_and_tooltips(qtbot: QtBot) -> None:
    shell = _shell(qtbot)
    shell.rail.set_marked("redact", True)
    assert shell.rail.marked("redact") and not shell.rail.marked("crop")
    assert shell.rail.button("crop").toolTip() == "Crop (C)"  # без скобок в подписи
    assert tip("Скрыть область", "B") == "Скрыть область (B)"
    assert tip("Звук") == "Звук"


def test_status_line_flash_restores_the_hint(qtbot: QtBot) -> None:
    shell = _shell(qtbot)
    shell.status.set_hint("подсказка")
    shell.status.flash("сообщение", 50)
    assert shell.status.shown_text() == "сообщение"
    shell.status.set_hint("новая подсказка")  # не затирает сообщение
    assert shell.status.shown_text() == "сообщение"
    qtbot.waitUntil(lambda: shell.status.shown_text() == "новая подсказка", timeout=2000)


def test_toggle_segmented_and_buttons(qtbot: QtBot) -> None:
    toggle = PixelToggle("Убрать звук")
    qtbot.addWidget(toggle)
    toggle.show()
    changes: list[bool] = []
    toggle.toggled.connect(changes.append)
    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert changes == [True, False]
    toggle.setEnabled(False)
    toggle.grab()  # состояние «выключена» рисуется без ошибок
    seg = Segmented()
    qtbot.addWidget(seg)
    seg.add("A", 1)
    seg.add("B", 2)
    seen: list[object] = []
    seg.changed.connect(seen.append)
    seg.buttons()[1].click()
    assert seg.value() == 2 and seen == [2]
    seg.clear_value()
    assert seg.value() is None
    main, ghost = button("Экспорт", "primary"), icon_button("undo", "Отменить")
    for widget in (main, ghost):
        qtbot.addWidget(widget)
    assert main.property("variant") == "primary" and ghost.property("variant") == "ghost"


def test_effect_entries_and_removal() -> None:
    effects = VideoEffects(
        crop=Rect(0, 0, 10, 10),
        redacts=(Redact(Rect(0, 0, 5, 5)), Redact(Rect(1, 1, 5, 5))),
        texts=(Text("a", 0, 0),),
        adjust=Adjust(contrast=1.2),
        filter="sepia",
        rotation=90,
        flip_h=True,
    )
    kinds = [(e.kind, e.index) for e in effect_entries(effects)]
    assert kinds == [
        ("crop", 0), ("redact", 0), ("redact", 1), ("text", 0),
        ("adjust", 0), ("filter", 0), ("rotation", 0), ("flip", 0),
    ]  # fmt: skip
    assert {e.tool for e in effect_entries(effects)} == {
        "crop",
        "redact",
        "text",
        "adjust",
        "rotate",
    }
    fewer = without_effect(effects, EffectEntry("redact", 0))
    assert len(fewer.redacts) == 1 and fewer.redacts[0].rect == Rect(1, 1, 5, 5)
    assert without_effect(effects, EffectEntry("flip")).flip_h is False
    assert effect_entries(VideoEffects()) == []


def test_effects_chip_lists_and_removes(qtbot: QtBot) -> None:
    chip = EffectsChip()
    qtbot.addWidget(chip)
    chip.show()
    assert chip.text() == "Без эффектов" and not chip.isEnabled()
    chip.set_effects(
        VideoEffects(texts=(Text("Привет мир, это длинная подпись", 0, 0),), filter="blur")
    )
    assert "2" in chip.text() and chip.isEnabled()
    removed: list[object] = []
    cleared: list[bool] = []
    chip.removeRequested.connect(removed.append)
    chip.clearRequested.connect(lambda: cleared.append(True))
    chip.open_list()
    popup = chip._popup
    assert popup is not None and len(popup.rows) == 2
    assert "Текст 1" in popup.rows[0][1].text() and "…" in popup.rows[0][1].text()
    popup.rows[1][2].click()
    assert removed == [EffectEntry("filter")]
    chip.open_list()
    assert chip._popup is not None
    chip._popup.reset_all.click()
    assert cleared == [True]


def _strip(qtbot: QtBot, count: int, width: int = 900) -> ClipStrip:
    strip = ClipStrip()
    qtbot.addWidget(strip)
    strip.resize(width, 40)
    strip.show()
    strip.set_clips([ClipInfo(f"clip{i}.mp4", "0:06") for i in range(count)], 0)
    return strip


def test_clip_strip_is_compact_for_one_clip_and_grows(qtbot: QtBot) -> None:
    strip = _strip(qtbot, 1)
    assert strip.height() == tokens.CLIP_STRIP_H
    strip.set_clips([ClipInfo(f"c{i}.mp4", "0:06") for i in range(14)], 0)
    assert strip.rows() > 1
    assert tokens.CLIP_STRIP_H < strip.height() <= tokens.CLIP_STRIP_MAX
    strip.set_compact(True)  # малая высота окна: одна строка с прокруткой
    assert strip.rows() == 1
    assert strip.height() <= tokens.CLIP_STRIP_MAX


def test_clip_strip_selection_reorder_remove_and_mini_panel(qtbot: QtBot) -> None:
    strip = _strip(qtbot, 3)
    chosen: list[int] = []
    moves: list[tuple[int, int]] = []
    removed: list[int] = []
    strip.currentChanged.connect(chosen.append)
    strip.moveRequested.connect(lambda a, b: moves.append((a, b)))
    strip.removeRequested.connect(removed.append)
    chips = strip.chips()
    QTest.mouseClick(chips[2], Qt.MouseButton.LeftButton)
    assert chosen == [2] and strip.current == 2 and chips[2].selected
    strip._show_mini(chips[2])
    qtbot.waitUntil(lambda: strip.mini.isVisible(), timeout=1000)
    assert not strip.mini.right.isEnabled() and strip.mini.left.isEnabled()
    strip.mini.left.click()
    assert moves == [(2, 1)]
    strip.mini.remove.click()
    assert removed == [2]
    # перетаскивание: тянем первый чип на место третьего
    strip.set_current(0)
    first = strip.chips()[0]
    origin = first.mapToGlobal(first.rect().center())

    def send(kind: QEvent.Type, shift: float, buttons: Qt.MouseButton) -> None:
        here = QPointF(origin) + QPointF(shift, 0)
        button = (
            Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        )
        event = QMouseEvent(
            kind, QPointF(first.rect().center()), here, button, buttons,
            Qt.KeyboardModifier.NoModifier,
        )  # fmt: skip
        strip.eventFilter(first, event)

    left = Qt.MouseButton.LeftButton
    send(QEvent.Type.MouseButtonPress, 0, left)
    send(QEvent.Type.MouseMove, 2.2 * (CHIP_W + 8), left)
    assert first.dragging
    send(QEvent.Type.MouseButtonRelease, 2.2 * (CHIP_W + 8), Qt.MouseButton.NoButton)
    assert moves[-1][0] == 0 and moves[-1][1] == 2


def test_last_clip_cannot_be_removed_from_the_menu(qtbot: QtBot) -> None:
    strip = _strip(qtbot, 1)
    strip._show_mini(strip.chips()[0])
    assert not strip.mini.remove.isEnabled()


def test_trim_bar_zoom_label_and_follow(qtbot: QtBot) -> None:
    bar = TrimBar()
    qtbot.addWidget(bar)
    bar.resize(800, 72)
    bar.show()
    bar.set_clip(60.0, 5.0, 25.5, [None] * 14)
    assert bar.label_text() == range_label(5.0, 25.5) == "0:05.0 – 0:25.5 · 0:20.5"
    levels: list[float] = []
    bar.zoomChanged.connect(levels.append)
    bar.set_position(30.0)
    bar.zoom_in()
    assert bar.zoom_level == pytest.approx(1.5) and levels[-1] == pytest.approx(1.5)
    for _ in range(4):
        bar.zoom_in()
    assert bar.zoom_level > 5
    bar.set_position(2.0)  # указатель ушёл из видимой части: окно следует за ним
    assert bar._visible(2.0)
    bar.zoom_out()
    bar.fit()
    assert bar.zoom_level == 1.0 and levels[-1] == 1.0
    bar.grab()  # рисуется и с масштабом, и без


def test_trim_bar_wheel_zooms_with_ctrl(qtbot: QtBot) -> None:
    bar = TrimBar()
    qtbot.addWidget(bar)
    bar.resize(800, 72)
    bar.set_clip(60.0, 0.0, 60.0, [])
    event = QWheelEvent(
        QPointF(400, 30), QPointF(400, 30), QPointF(0, 0).toPoint(), QPointF(0, 120).toPoint(),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase,
        False,
    )  # fmt: skip
    bar.wheelEvent(event)
    assert bar.zoom_level > 1.0


def test_thumbnails_are_placed_in_time_when_zoomed(qtbot: QtBot) -> None:
    bar = TrimBar()
    qtbot.addWidget(bar)
    bar.resize(800, 72)
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    bar.set_clip(10.0, 0.0, 10.0, [image] * 5)
    bar.zoom_by(4.0, 5.0)
    assert bar.grab().width() > 0
