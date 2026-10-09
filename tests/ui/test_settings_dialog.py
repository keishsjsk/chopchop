from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from chopchop.core import settings_schema as schema
from chopchop.services.app_settings import AppSettings
from chopchop.ui.settings_dialog import SettingsDialog


def _dialog(qtbot: QtBot, path: Path | None = None) -> tuple[SettingsDialog, AppSettings]:
    settings = AppSettings(path)
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog, settings


def _widget(dialog: SettingsDialog, key: str, kind: type) -> object:
    return dialog._rows[key].widget.findChild(kind) or dialog._rows[key].widget


def test_lists_sections_with_visible_settings_only(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    titles = [dialog._sections.item(i).text() for i in range(dialog._sections.count())]
    assert titles[0] == "Основные"
    assert "Воспроизведение" in titles and "Фото" in titles and "Редактор" in titles
    assert "Дополнительно" in titles
    assert "Внешний вид" in titles
    hidden = {s.key for s in schema.SPECS if not s.shown}
    assert hidden.isdisjoint(dialog._rows)


def test_every_shown_setting_has_a_control(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    shown = {s.key for s in schema.SPECS if s.shown}
    assert shown == set(dialog._rows)


def test_changing_controls_updates_settings_immediately(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    seek = _widget(dialog, "playback.seek_short", QSpinBox)
    assert isinstance(seek, QSpinBox)
    seek.setValue(12)
    assert settings.get_int("playback.seek_short") == 12
    step = dialog._rows["photo.zoom_step"].widget
    assert isinstance(step, QDoubleSpinBox)
    step.setValue(1.5)
    assert settings.get_float("photo.zoom_step") == 1.5
    strip = dialog._rows["editor.strip_metadata"].widget
    assert isinstance(strip, QCheckBox)
    strip.setChecked(False)
    assert not settings.get_bool("editor.strip_metadata")
    combo = dialog._rows["photo.wheel_action"].widget
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData("navigate"))
    assert settings.get_str("photo.wheel_action") == "navigate"


def test_text_setting_is_saved_when_editing_finishes(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    edit = dialog._rows["playback.audio_langs"].widget
    assert isinstance(edit, QLineEdit)
    edit.setText("jpn, eng")
    edit.editingFinished.emit()
    assert settings.get_str("playback.audio_langs") == "jpn,eng"


def test_invalid_template_is_reported_and_not_saved(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    dialog._sections.setCurrentRow(dialog._page_sections.index("editor"))
    edit = dialog._rows["editor.output_template"].widget
    assert isinstance(edit, QLineEdit)
    edit.setText("no placeholder")
    edit.editingFinished.emit()
    assert settings.get_str("editor.output_template") == "{name}_edited"
    assert dialog._errors["editor.output_template"].isVisibleTo(dialog)
    edit.setText("{name}_v2")
    edit.editingFinished.emit()
    assert settings.get_str("editor.output_template") == "{name}_v2"
    assert not dialog._errors["editor.output_template"].isVisibleTo(dialog)


def test_outside_changes_are_shown_without_echo(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    changes: list[str] = []
    settings.changed.connect(lambda key, _v: changes.append(key))
    settings.set("playback.seek_short", 9)
    spin = dialog._rows["playback.seek_short"].widget
    assert isinstance(spin, QSpinBox) and spin.value() == 9
    assert changes == ["playback.seek_short"]  # окно не отправило значение обратно


def test_reset_section_updates_the_controls(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 40)
    settings.set("photo.zoom_step", 1.9)
    settings.reset_section("playback")
    spin = dialog._rows["playback.seek_short"].widget
    assert isinstance(spin, QSpinBox) and spin.value() == 5
    zoom = dialog._rows["photo.zoom_step"].widget
    assert isinstance(zoom, QDoubleSpinBox) and zoom.value() == 1.9


def test_reset_all_asks_first(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 40)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog._reset_all()
    assert settings.get_int("playback.seek_short") == 40
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._reset_all()
    assert settings.get_int("playback.seek_short") == 5


def test_restart_note_appears_only_for_restart_settings(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    assert not dialog._restart_note.isVisibleTo(dialog)
    settings.set("playback.seek_short", 7)
    assert not dialog._restart_note.isVisibleTo(dialog)
    combo = dialog._rows["general.language"].widget
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData("en"))
    assert dialog._restart_note.isVisibleTo(dialog)


def test_advanced_settings_are_collapsed_until_asked(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    row = dialog._rows["advanced.threads"].widget
    page_index = dialog._page_sections.index("advanced")
    dialog._sections.setCurrentRow(page_index)
    assert not row.isVisibleTo(dialog)
    page = dialog._pages.currentWidget()
    assert page is not None
    toggles = page.findChildren(QToolButton)
    toggles[0].click()
    assert row.isVisibleTo(dialog)
    toggles[0].click()
    assert not row.isVisibleTo(dialog)


def test_export_then_import_in_another_store(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 33)
    target = tmp_path / "out.toml"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog._export()
    assert target.exists()
    other_dialog, other = _dialog(qtbot)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    other_dialog._import()
    assert other.get_int("playback.seek_short") == 33
    spin = other_dialog._rows["playback.seek_short"].widget
    assert isinstance(spin, QSpinBox) and spin.value() == 33
    assert "загружены" in other_dialog._status.text()


def test_importing_a_broken_file_shows_a_message(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog, settings = _dialog(qtbot)
    broken = tmp_path / "broken.toml"
    broken.write_text("= = =", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(broken), ""))
    dialog._import()
    assert "Не удалось" in dialog._status.text()
    assert settings.get_int("playback.seek_short") == 5


def test_clear_cache_button_reports(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    dialog._clear_cache()
    assert "очищен" in dialog._status.text()
