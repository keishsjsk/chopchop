"""Окно настроек: разделы, поиск, элементы управления, применение на лету, сброс, размер."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QMessageBox, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from chopchop.core import settings_schema as schema
from chopchop.services.app_settings import AppSettings
from chopchop.ui.settings_dialog import GROUPS, SettingsDialog
from chopchop.ui.settings_widgets import (
    NumberControl,
    SegmentControl,
    SelectControl,
    SettingCard,
    SliderControl,
    TextControl,
    ToggleControl,
)
from chopchop.ui.theme import tokens


def _page(dialog: SettingsDialog) -> QWidget:
    page = dialog.pages.currentWidget()
    assert page is not None
    return page


def _dialog(qtbot: QtBot, path: Path | None = None) -> tuple[SettingsDialog, AppSettings]:
    settings = AppSettings(path)
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog, settings


def test_every_section_opens_with_its_page(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    titles = [item.text() for item in dialog.nav.items]
    assert titles[0] == "Основные" and "Субтитры" in titles and titles[-1] == "Дополнительно"
    assert dialog.page_sections == [item.section for item in dialog.nav.items]
    for section in dialog.page_sections:
        dialog.open_section(section)
        assert dialog.current_section() == section
        assert dialog.pages.currentWidget() is dialog._scrolls[section]
        assert not dialog.grab().isNull()  # страница рисуется без ошибок


def test_every_shown_setting_has_a_row_in_a_group(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    shown = {s.key for s in schema.SPECS if s.shown}
    assert shown == set(dialog.rows)
    grouped = {key for groups in GROUPS.values() for _title, keys in groups for key in keys}
    assert shown <= grouped, "настройка без группы попала бы в «Прочее»"
    hidden = {s.key for s in schema.SPECS if not s.shown}
    assert hidden.isdisjoint(dialog.rows)


def test_rows_are_at_least_48_px_high_and_carry_descriptions(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    dialog.open_section("photo")
    row = dialog.rows["photo.zoom_step"]
    assert row.minimumHeight() == 48 and row.height() >= 48
    assert row.description.isVisibleTo(dialog) == bool(row.description.text())
    assert dialog.rows["general.confirm_delete"].description.text()  # пояснение под названием


def test_controls_have_the_expected_kinds(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    assert isinstance(dialog.rows["editor.strip_metadata"].control, ToggleControl)
    assert isinstance(dialog.rows["playback.seek_short"].control, SliderControl)
    assert isinstance(dialog.rows["playback.seek_long"].control, NumberControl)  # 595 шагов
    assert isinstance(dialog.rows["general.language"].control, SegmentControl)  # два коротких
    assert isinstance(dialog.rows["general.open_mode"].control, SelectControl)  # длинные подписи
    assert isinstance(dialog.rows["editor.crop_ratio"].control, SelectControl)  # много вариантов
    assert isinstance(dialog.rows["playback.audio_langs"].control, TextControl)


def test_changing_controls_updates_settings_immediately(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    slider = dialog.rows["playback.seek_short"].control
    assert isinstance(slider, SliderControl)
    slider.slider.setValue(slider.slider.maximum())
    assert settings.get_int("playback.seek_short") == int(
        schema_spec("playback.seek_short").high or 0
    )
    zoom = dialog.rows["photo.zoom_step"].control
    assert isinstance(zoom, SliderControl)
    zoom.slider.setValue(zoom.slider.minimum())
    assert settings.get_float("photo.zoom_step") == pytest.approx(
        schema_spec("photo.zoom_step").low
    )
    toggle = dialog.rows["editor.strip_metadata"].control
    assert isinstance(toggle, ToggleControl)
    toggle.toggle.setChecked(False)
    assert not settings.get_bool("editor.strip_metadata")
    select = dialog.rows["photo.wheel_action"].control
    assert isinstance(select, (SelectControl, SegmentControl))
    if isinstance(select, SelectControl):
        select.choose("navigate")
    else:
        select.segments.set_value("navigate", emit=True)
    assert settings.get_str("photo.wheel_action") == "navigate"
    number = dialog.rows["playback.seek_long"].control
    assert isinstance(number, NumberControl)
    before = settings.get_int("playback.seek_long")
    number.plus.click()
    assert settings.get_int("playback.seek_long") == before + 1
    number.minus.click()
    number.minus.click()
    assert settings.get_int("playback.seek_long") == before - 1


def schema_spec(key: str) -> schema.Spec:
    return next(s for s in schema.SPECS if s.key == key)


def test_select_opens_a_themed_menu_and_keys_change_the_value(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    dialog.open_section("editor")
    select = dialog.rows["editor.crop_ratio"].control
    assert isinstance(select, SelectControl)
    menu = select.open_menu()
    assert menu.property("themed") is True
    titles = [a.text() for a in menu.actions()]
    assert "1:1" in titles and len(titles) == len(schema_spec("editor.crop_ratio").choices)
    menu.close()
    start = select.value()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    select.eventFilter(select.button, event)
    assert select.value() != start
    assert settings.get_str("editor.crop_ratio") == select.value()


def test_text_setting_is_saved_when_editing_finishes(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    control = dialog.rows["playback.audio_langs"].control
    assert isinstance(control, TextControl)
    control.edit.setText("jpn, eng")
    control.edit.editingFinished.emit()
    assert settings.get_str("playback.audio_langs") == "jpn,eng"


def test_invalid_template_is_reported_on_its_row_and_not_saved(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    dialog.open_section("editor")
    row = dialog.rows["editor.output_template"]
    control = row.control
    assert isinstance(control, TextControl)
    control.edit.setText("no placeholder")
    control.edit.editingFinished.emit()
    assert settings.get_str("editor.output_template") == "{name}_edited"
    assert row.error.isVisibleTo(dialog)
    control.edit.setText("{name}_v2")
    control.edit.editingFinished.emit()
    assert settings.get_str("editor.output_template") == "{name}_v2"
    assert not row.error.isVisibleTo(dialog)


def test_outside_changes_are_shown_without_echo(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    changes: list[str] = []
    settings.changed.connect(lambda key, _v: changes.append(key))
    settings.set("playback.seek_short", 9)
    control = dialog.rows["playback.seek_short"].control
    assert isinstance(control, SliderControl) and control.value() == 9
    assert changes == ["playback.seek_short"]  # окно не отправило значение обратно


def test_reset_section_updates_the_controls(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 40)
    settings.set("playback.volume_step", 25)
    settings.reset_section("playback")
    control = dialog.rows["playback.seek_short"].control
    assert isinstance(control, SliderControl) and control.value() == 5
    dialog.open_section("playback")
    page_buttons = [b.text() for b in _page(dialog).findChildren(QPushButton)]
    assert "Сбросить раздел" in page_buttons  # внизу каждого раздела


def test_reset_section_button_resets_only_its_section(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 40)
    settings.set("photo.preload", 4)
    dialog.open_section("playback")
    button = next(
        b for b in _page(dialog).findChildren(QPushButton) if b.text() == "Сбросить раздел"
    )
    button.click()
    assert settings.get_int("playback.seek_short") == 5
    assert settings.get_int("photo.preload") == 4  # другой раздел не тронут


def test_reset_all_asks_first(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    dialog, settings = _dialog(qtbot)
    settings.set("playback.seek_short", 40)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog._reset_all()
    assert settings.get_int("playback.seek_short") == 40
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._reset_all()
    assert settings.get_int("playback.seek_short") == 5


def test_restart_chip_and_note_only_for_restart_settings(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    assert dialog.rows["general.language"].chip is not None
    assert dialog.rows["general.language"].chip.text() == "после перезапуска"
    assert dialog.rows["playback.seek_short"].chip is None
    assert not dialog._restart_note.isVisibleTo(dialog)
    settings.set("playback.seek_short", 7)
    assert not dialog._restart_note.isVisibleTo(dialog)
    language = dialog.rows["general.language"].control
    assert isinstance(language, SegmentControl)
    language.segments.set_value("en", emit=True)
    assert dialog._restart_note.isVisibleTo(dialog)


def test_search_finds_a_row_shows_its_section_and_goes_to_it(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    dialog.search.setText("кэш")
    qtbot.waitUntil(lambda: dialog.pages.currentWidget() is dialog._results_scroll, timeout=2000)
    assert "advanced.thumb_cache_mb" in dialog._results_keys
    row = dialog._found["advanced.thumb_cache_mb"][0]
    assert row.isVisibleTo(dialog)
    crumbs = [
        lbl.text() for lbl in row.findChildren(type(row.title)) if lbl.property("chip") == "muted"
    ]
    assert crumbs == ["Дополнительно"]  # в результатах виден раздел
    # строка в результатах рабочая
    control = row.control
    assert isinstance(control, SliderControl)
    control.slider.setValue(control.slider.maximum())
    assert settings.get_int("advanced.thumb_cache_mb") == 5000
    assert dialog.rows["advanced.thumb_cache_mb"].control.value() == 5000  # type: ignore[attr-defined]
    row.activated.emit()  # щелчок по названию: переход
    assert dialog.current_section() == "advanced"
    assert dialog.pages.currentWidget() is dialog._scrolls["advanced"]
    target = dialog.rows["advanced.thumb_cache_mb"]
    qtbot.waitUntil(lambda: target._flash, timeout=2000)  # строка подсвечена
    assert dialog.search.text() == ""


def test_search_by_choice_title_and_empty_result(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    assert "photo.smoothing" in dialog.search_for("сглаживание")
    assert dialog.search_for("   ") == []
    dialog.search.setText("такого-нет-нигде")
    qtbot.waitUntil(lambda: dialog.pages.currentWidget() is dialog._results_scroll, timeout=2000)
    assert dialog._results_keys == []
    dialog.search.clear()
    qtbot.waitUntil(
        lambda: dialog.pages.currentWidget() is not dialog._results_scroll, timeout=2000
    )


def test_enter_in_search_opens_the_first_result_and_ctrl_f_focuses_search(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    dialog.search.setText("громкость")
    qtbot.waitUntil(lambda: bool(dialog._results_keys), timeout=2000)
    dialog.search.returnPressed.emit()
    assert dialog.current_section() == "playback"
    dialog.focus_search()
    assert dialog.focusWidget() is dialog.search or dialog.search.hasFocus()


def test_subtitle_settings_are_found_but_open_their_page(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    dialog.search.setText("контур")
    qtbot.waitUntil(lambda: dialog.pages.currentWidget() is dialog._results_scroll, timeout=2000)
    assert any(key.startswith("subtitles.") for key in dialog._results_keys)
    dialog.go_to(next(k for k in dialog._results_keys if k.startswith("subtitles.")))
    assert dialog.current_section() == "subtitles"


def test_arrow_keys_move_between_sections(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    first = dialog.nav.items[0]
    first.setFocus()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    assert dialog.nav.eventFilter(first, event)
    assert dialog.current_section() == dialog.page_sections[1]
    up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    assert dialog.nav.eventFilter(dialog.nav.items[1], up)
    assert dialog.current_section() == dialog.page_sections[0]


def test_footer_has_the_listed_buttons_and_no_ok_or_cancel(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    texts = [
        dialog.import_button.text(),
        dialog.export_button.text(),
        dialog.reset_all_button.text(),
        dialog.folder_button.text(),
        dialog.close_button.text(),
    ]
    assert texts == ["Импорт…", "Экспорт…", "Сбросить всё…", "Открыть папку настроек", "Закрыть"]
    assert dialog.findChildren(QDialogButtonBox) == []


def test_window_size_default_minimum_and_memory(qtbot: QtBot) -> None:
    dialog, settings = _dialog(qtbot)
    assert (dialog.width(), dialog.height()) == (860, 600)
    assert (dialog.minimumWidth(), dialog.minimumHeight()) == (720, 480)
    dialog.resize(900, 640)
    dialog.done(0)
    assert settings.get_str("state.settings_size") == "900x640"
    again = SettingsDialog(settings)
    qtbot.addWidget(again)
    assert (again.width(), again.height()) == (900, 640)
    settings.set("state.settings_size", "100x100")
    smaller = SettingsDialog(settings)
    qtbot.addWidget(smaller)
    assert smaller.width() >= 720 and smaller.height() >= 480  # меньше минимума не бывает


def test_left_panel_is_220_wide_with_40_px_items_and_a_divider(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    assert dialog.nav.width() == 220
    assert all(item.height() == 40 for item in dialog.nav.items)
    advanced = dialog.nav.items[-1]
    previous = dialog.nav.items[-2]
    assert advanced.geometry().top() - previous.geometry().bottom() > 1  # разделитель между ними


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
    control = other_dialog.rows["playback.seek_short"].control
    assert isinstance(control, SliderControl) and control.value() == 33
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


def test_advanced_section_marks_dangerous_actions(qtbot: QtBot) -> None:
    dialog, _ = _dialog(qtbot)
    dialog.open_section("advanced")
    cards = [c for c in _page(dialog).findChildren(SettingCard) if c._danger]
    assert cards, "карточка опасных действий с предупреждающей рамкой"
    buttons = [b.text() for b in cards[0].findChildren(QPushButton)]
    assert "Очистить кэш миниатюр" in buttons and "Сбросить все настройки…" in buttons
    dialog._clear_cache()
    assert "очищен" in dialog._status.text()


# --- контраст: выбранный пункт и описания в обеих темах ---------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_selected_item_and_descriptions_are_readable(theme: str) -> None:
    p = tokens.PALETTES[theme]
    assert tokens.contrast(p.text, p.accent_tint) >= 4.5  # выбранный пункт: обычный текст
    assert tokens.contrast(p.text, p.surface_raised) >= 4.5  # наведение
    assert tokens.contrast(p.text_muted, p.surface) >= 4.5  # описание в карточке
    assert tokens.contrast(p.text_muted, p.bg) >= 4.5  # описание на фоне страницы
    assert tokens.contrast(p.accent, p.surface) >= 3.0  # полоса акцента рядом с панелью
    assert tokens.contrast(p.focus_ring, p.surface) >= 3.0  # кольцо фокуса
    assert (
        tokens.contrast(p.text, p.accent_tint) >= 4.5 and tokens.contrast(p.text, p.surface) >= 4.5
    )


def test_accent_default_is_ember_and_old_names_migrate() -> None:
    from chopchop.core.settings_schema import BY_KEY, coerce
    from chopchop.ui.theme import tokens

    spec = BY_KEY["appearance.accent"]
    assert spec.default == tokens.DEFAULT_ACCENT == "ember"
    assert set(tokens.ACCENTS) == {"ember", "meadow", "sunset", "rose"}
    assert coerce(spec, "violet") == "meadow" and coerce(spec, "orange") == "ember"
