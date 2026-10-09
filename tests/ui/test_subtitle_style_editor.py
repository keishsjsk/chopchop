from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog
from pytestqt.qtbot import QtBot

from chopchop.core.subtitle_style import BUILTIN, SubtitleStyle
from chopchop.player.player import Player
from chopchop.services.app_settings import AppSettings
from chopchop.services.settings import subtitle_style
from chopchop.services.sub_presets import PresetStore
from chopchop.ui.settings_dialog import SettingsDialog
from chopchop.ui.subtitle_style_editor import SubtitlePreview, SubtitleStyleEditor
from chopchop.ui.tracks_panel import TracksPanel
from fakes import FakeMpv


def _editor(
    qtbot: QtBot, compact: bool = False, store: PresetStore | None = None
) -> tuple[SubtitleStyleEditor, AppSettings]:
    settings = AppSettings(None)
    editor = SubtitleStyleEditor(settings, store or PresetStore(None), compact=compact)
    qtbot.addWidget(editor)
    editor.show()
    return editor, settings


def test_controls_write_settings_immediately(qtbot: QtBot) -> None:
    editor, settings = _editor(qtbot)
    editor._size.setValue(80)
    editor._bold.setChecked(True)
    editor._outline.setValue(5.5)
    editor._margin_y.setValue(60)
    editor._pos.setValue(80)
    editor._back.setChecked(True)
    editor._back_opacity.setValue(40)
    editor._align_y.buttons()[0].click()  # сверху
    editor._mode.buttons()[2].click()  # моё оформление
    style = subtitle_style(settings)
    assert (style.font_size, style.bold, style.outline_size) == (80, True, 5.5)
    assert (style.margin_y, style.pos, style.back_enabled, style.back_opacity) == (60, 80, True, 40)
    assert style.align_y == "top" and style.ass_mode == "mine"
    assert editor.preview._style == style  # образец следует за настройками


def test_widgets_follow_settings_changes_and_reset(qtbot: QtBot) -> None:
    editor, settings = _editor(qtbot)
    settings.set("subtitles.font_size", 99)
    settings.set("subtitles.color", "#ff0000")
    assert editor._size.value() == 99
    assert editor._color_text.color == (255, 0, 0)
    settings.reset_section("subtitles")
    assert editor._size.value() == 55 and editor._color_text.color == (255, 255, 255)


def test_font_search_and_cyrillic_warning(qtbot: QtBot) -> None:
    editor, settings = _editor(qtbot)
    assert editor._font.itemData(0) == ""  # первый пункт — шрифт по умолчанию
    assert editor._font.completer() is not None  # поиск по части названия
    line = editor._font.lineEdit()
    assert line is not None
    line.setText("Нет такого шрифта 123")
    editor._font_typed()
    assert settings.get_str("subtitles.font") == "Нет такого шрифта 123"
    assert not editor._font_note.isHidden()  # шрифта в системе нет: об этом сказано
    line = editor._font.lineEdit()
    assert line is not None
    line.setText("")
    editor._font_typed()
    assert settings.get_str("subtitles.font") == "" and editor._font_note.isHidden()


def test_private_interface_font_is_not_offered(qtbot: QtBot) -> None:
    from chopchop.ui.theme import fonts

    editor, _ = _editor(qtbot)
    names = [editor._font.itemText(i) for i in range(editor._font.count())]
    assert fonts.PIXEL_FAMILY not in names  # шрифт самой программы libass не видит


def test_presets_apply_save_delete(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    editor, settings = _editor(qtbot)
    index = editor._preset.findData("Высокий контраст")
    editor._preset.setCurrentIndex(index)
    editor._on_preset_chosen(index)
    assert subtitle_style(settings) == BUILTIN["Высокий контраст"]
    assert editor._preset.currentData() == "Высокий контраст"
    assert not editor._delete.isEnabled()  # встроенный не удалить
    editor._size.setValue(61)  # вручную: пресет больше не совпадает
    assert editor._preset.currentData() == "\0custom"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Мой", True))
    editor.save_preset()
    assert editor._preset.currentData() == "Мой" and editor._delete.isEnabled()
    editor.delete_preset()
    assert "Мой" not in editor._presets.names()


def test_import_and_export_json(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PresetStore(tmp_path / "p.json")
    editor, settings = _editor(qtbot, store=store)
    editor._size.setValue(72)
    target = tmp_path / "out.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    editor.export_presets()
    assert target.is_file()
    other, other_settings = _editor(qtbot, store=PresetStore(tmp_path / "q.json"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    other.import_presets()
    assert other_settings.get_int("subtitles.font_size") == 72  # импортированное применено
    assert other._presets.user  # и осталось в списке
    assert settings.get_int("subtitles.font_size") == 72


def test_preview_paints_every_alignment_and_box(qtbot: QtBot) -> None:
    preview = SubtitlePreview()
    qtbot.addWidget(preview)
    preview.resize(400, 150)
    for style in (
        SubtitleStyle(align_x="left", align_y="top"),
        SubtitleStyle(align_x="right", align_y="center", back_enabled=True, shadow_offset=3),
        SubtitleStyle(font="Arial", bold=True, italic=True, line_spacing=10),
    ):
        preview.set_style(style)
        assert not preview.grab().isNull()


def test_compact_editor_has_the_essentials_and_a_way_to_the_full_page(qtbot: QtBot) -> None:
    editor, _ = _editor(qtbot, compact=True)
    assert hasattr(editor, "_size") and hasattr(editor, "_color_text")
    assert not hasattr(editor, "_shadow")
    asked: list[bool] = []
    editor.openAllRequested.connect(lambda: asked.append(True))
    from PySide6.QtWidgets import QPushButton

    more = next(b for b in editor.findChildren(QPushButton) if "Все настройки" in b.text())
    more.click()
    assert asked == [True]


def test_image_subtitles_disable_style_controls_and_explain(qtbot: QtBot) -> None:
    editor, _ = _editor(qtbot)
    editor.set_track_kind(True)
    assert not editor._size.isEnabled() and not editor._color_text.isEnabled()
    assert editor._pos.isEnabled() and editor._scale.isEnabled()  # положение и масштаб остаются
    assert "PGS" in editor._notice.text() and not editor._notice.isHidden()
    editor.set_track_kind(False)
    assert editor._size.isEnabled() and editor._notice.isHidden()
    editor.set_unsupported({"sub_line_spacing"})
    assert "sub-line-spacing" in editor._notice.text()


def test_tracks_panel_detects_picture_subtitles(qtbot: QtBot) -> None:
    fake = FakeMpv()
    fake.track_list = [
        {"id": 1, "type": "sub", "codec": "hdmv_pgs_subtitle", "selected": True},
        {"id": 2, "type": "sub", "codec": "subrip"},
    ]
    fake.sid = 1
    player = Player(fake)
    settings = AppSettings(None)
    panel = TracksPanel(player, None, settings, PresetStore(None))
    qtbot.addWidget(panel)
    editor = panel.style_editor()
    assert editor is not None
    assert not editor._size.isEnabled()  # выбраны картинки: стиль неприменим
    fake.sid = 2
    player.tracksChanged.emit()
    assert editor._size.isEnabled()
    player.apply_style(SubtitleStyle(), "auto", 0)
    panel.rebuild()
    assert editor._notice.isHidden()


def test_settings_dialog_has_the_subtitles_page(qtbot: QtBot) -> None:
    settings = AppSettings(None)
    dialog = SettingsDialog(settings, None, PresetStore(None))
    qtbot.addWidget(dialog)
    titles = [dialog._sections.item(i).text() for i in range(dialog._sections.count())]
    assert "Субтитры" in titles
    dialog.open_section("subtitles")
    assert dialog._sections.currentItem().text() == "Субтитры"
    dialog.subtitle_editor._size.setValue(77)
    assert settings.get_int("subtitles.font_size") == 77
