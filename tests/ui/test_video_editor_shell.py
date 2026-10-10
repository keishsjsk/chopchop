"""Оболочка редактора, семейство кнопок, полоса клипов, полоса обрезки, чип эффектов."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, Redact, Text
from chopchop.core.video import EffectEntry, VideoEffects, effect_entries, without_effect
from chopchop.ui.editor_shell import EditorShell
from chopchop.ui.effects_chip import EffectsChip
from chopchop.ui.theme import tokens
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
    assert shell.top.height() == tokens.TOP_BAR_H == 40
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


def test_button_icons_use_whole_pixel_scales(qtbot: QtBot) -> None:
    from PySide6.QtGui import QPixmap

    from chopchop.ui.theme import current, icons

    for ratio in (1.0, 1.5, 2.0, 3.0):
        for name in ("undo", "play", "step_back", "zoom_in", "reset_trim", "add_clip"):
            pix: QPixmap = icons.pixmap(name, current.palette(), logical=32, ratio=ratio)
            assert pix.width() % 16 == 0, (name, ratio)  # целое число пикселей сетки на пиксель
    button_ = icon_button("undo", "Отменить")
    qtbot.addWidget(button_)
    assert button_.iconSize().width() == icons.ui_icon_size()  # 16-21 px, масштаб сетки целый
    assert button_.width() >= tokens.ICON_BUTTON or button_.minimumWidth() >= 0


def test_selected_segment_is_outlined_and_tinted_not_filled(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    from chopchop.ui.theme import current
    from chopchop.ui.theme.manager import ThemeManager

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    previous = app.styleSheet()
    manager = ThemeManager(app)
    try:
        manager.set_theme("light")
        seg = Segmented()
        qtbot.addWidget(seg)
        seg.add("A", 1)
        seg.add("B", 2)
        seg.set_value(1)
        seg.show()
        p = current.palette()
        image = seg.buttons()[0].grab().toImage()
        centre = image.pixelColor(image.width() // 2, 6).name()
        assert centre != p.accent.lower()  # сплошной акцентной заливки нет
        assert centre == p.accent_tint.lower()  # лёгкая тонировка
        assert image.pixelColor(1, image.height() // 2).name() == p.accent.lower()  # рамка
        main = button("Экспорт", "primary")
        qtbot.addWidget(main)
        main.show()
        assert (
            main.grab().toImage().pixelColor(8, 8).name() == p.accent.lower()
        )  # главная — заливка
    finally:
        manager.shutdown()
        app.setStyleSheet(previous)
