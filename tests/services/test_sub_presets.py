from pathlib import Path

import pytest

from chopchop.core.subtitle_style import BUILTIN, PresetFileError, SubtitleStyle
from chopchop.services.sub_presets import FILE_NAME, PresetStore


def test_save_reload_and_remove(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / FILE_NAME)
    assert store.names() == list(BUILTIN)
    style = SubtitleStyle(font="Arial", font_size=70)
    assert store.save_as("  Мой  ", style) == "Мой"
    assert PresetStore(tmp_path / FILE_NAME).get("Мой") == style  # пережил перезапуск
    assert store.name_of(style) == "Мой"
    assert store.name_of(SubtitleStyle(font_size=99)) is None  # свои настройки
    assert store.remove("Мой") and not store.remove("Мой")
    assert not store.remove("Кино")  # встроенные не удаляются
    assert PresetStore(tmp_path / FILE_NAME).user == {}


def test_builtin_name_is_not_overwritten(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / FILE_NAME)
    saved = store.save_as("Кино", SubtitleStyle(font_size=20))
    assert saved == "Кино (мой)" and store.get("Кино") == BUILTIN["Кино"]
    with pytest.raises(ValueError):
        store.save_as("   ", SubtitleStyle())


def test_broken_file_does_not_break_the_store(tmp_path: Path) -> None:
    path = tmp_path / FILE_NAME
    path.write_text("{ сломано", encoding="utf-8")
    store = PresetStore(path)
    assert store.user == {} and store.error
    store.save_as("Новый", SubtitleStyle())  # после этого файл снова в порядке
    assert PresetStore(path).get("Новый") is not None


def test_export_and_import_keep_both_sides_intact(tmp_path: Path) -> None:
    first = PresetStore(tmp_path / "a.json")
    first.save_as("Мой", SubtitleStyle(font_size=77))
    shared = tmp_path / "shared.json"
    first.export_to(shared)
    second = PresetStore(tmp_path / "b.json")
    second.save_as("Мой", SubtitleStyle(font_size=33))  # такое имя уже занято
    added = second.import_from(shared)
    assert "Мой (импорт)" in added
    assert second.get("Мой") == SubtitleStyle(font_size=33)
    assert second.get("Мой (импорт)") == SubtitleStyle(font_size=77)
    again = second.import_from(shared)  # повторный импорт не плодит копии
    assert again.count("Мой (импорт)") == 1 and len(second.user) == 2
    builtin_file = tmp_path / "builtin.json"
    PresetStore(None).export_to(builtin_file, dict(BUILTIN))  # встроенные в файле не дублируются
    assert second.import_from(builtin_file) == []
    with pytest.raises(ValueError):
        PresetStore(None).export_to(tmp_path / "empty.json")
    with pytest.raises(PresetFileError):
        shared.write_text("[]", encoding="utf-8")
        second.import_from(shared)


def test_memory_store_without_file() -> None:
    store = PresetStore(None)
    store.save_as("Временный", SubtitleStyle())
    assert "Временный" in store.names()
