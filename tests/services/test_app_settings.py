from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from chopchop.core.settings import SettingsFileError
from chopchop.services.app_settings import AppSettings


def _store(tmp_path: Path) -> AppSettings:
    return AppSettings(tmp_path / "settings.toml")


def test_defaults_when_there_is_no_file(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    assert settings.first_run
    assert settings.get_int("playback.volume_default") == 100
    assert settings.get_bool("playback.remember_position")
    assert not (tmp_path / "settings.toml").exists()  # пока ничего не меняли, файл не создаётся


def test_changes_are_saved_atomically_and_reloaded(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    assert settings.set("playback.seek_short", 10)
    assert settings.set("editor.output_dir", "D:/Фото")
    settings.flush()
    text = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "seek_short = 10" in text and "version = 1" in text
    assert not list(tmp_path.glob("*.tmp"))  # временный файл не остался
    again = _store(tmp_path)
    assert not again.first_run
    assert again.get_int("playback.seek_short") == 10
    assert again.get_str("editor.output_dir") == "D:/Фото"


def test_changes_are_signalled_once_and_same_value_is_ignored(qtbot: QtBot, tmp_path: Path) -> None:
    settings = _store(tmp_path)
    seen: list[tuple[str, object]] = []
    settings.changed.connect(lambda key, value: seen.append((key, value)))
    assert settings.set("photo.zoom_step", 1.5)
    assert not settings.set("photo.zoom_step", 1.5)
    assert seen == [("photo.zoom_step", 1.5)]


def test_saving_is_delayed_so_slider_drags_write_once(qtbot: QtBot, tmp_path: Path) -> None:
    settings = _store(tmp_path)
    for value in range(1, 8):
        settings.set("playback.seek_short", value)
    assert not (tmp_path / "settings.toml").exists()
    qtbot.waitUntil(lambda: (tmp_path / "settings.toml").exists(), timeout=3000)
    assert _store(tmp_path).get_int("playback.seek_short") == 7


def test_invalid_value_is_rejected_and_nothing_changes(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    with pytest.raises(ValueError):
        settings.set("general.language", "klingon")
    with pytest.raises(KeyError):
        settings.set("no.such", 1)
    assert settings.get_str("general.language") == "ru"


def test_broken_file_is_backed_up_and_defaults_used(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("this is = [not toml", encoding="utf-8")
    notices: list[str] = []
    settings = AppSettings.__new__(AppSettings)  # перехватить сообщение, отправленное при создании
    AppSettings.__init__(settings, None)
    settings.notice.connect(notices.append)
    settings._load(path)
    assert settings.get_int("playback.volume_default") == 100
    assert notices and "повреждён" in notices[0]
    backups = list(tmp_path.glob("settings.toml.broken-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "this is = [not toml"
    assert not path.exists()  # на месте битого файла чисто; новый появится при первом изменении


def test_file_from_the_future_is_treated_as_broken(tmp_path: Path) -> None:
    (tmp_path / "settings.toml").write_text("version = 7\n", encoding="utf-8")
    settings = _store(tmp_path)
    assert list(tmp_path.glob("settings.toml.broken-*"))
    assert settings.get_int("playback.seek_short") == 5


def test_oversized_file_is_not_parsed(tmp_path: Path) -> None:
    (tmp_path / "settings.toml").write_text("# " + "x" * 300_000, encoding="utf-8")
    _store(tmp_path)
    assert list(tmp_path.glob("settings.toml.broken-*"))


def test_reset_section_and_all(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    settings.set("playback.seek_short", 20)
    settings.set("photo.zoom_step", 1.9)
    settings.reset_section("playback")
    assert settings.get_int("playback.seek_short") == 5
    assert settings.get_float("photo.zoom_step") == 1.9
    settings.reset_all()
    assert settings.get_float("photo.zoom_step") == 1.25
    assert settings.is_default("photo.zoom_step")


def test_reset_all_keeps_window_state(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    settings.set("state.window", "abc")
    settings.reset_all()
    assert settings.get_str("state.window") == "abc"


def test_export_import_round_trip(qtbot: QtBot, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    source = _store(tmp_path / "a")
    source.set("playback.seek_short", 33)
    source.set("state.window", "geometry")
    target_file = tmp_path / "export.toml"
    source.export_to(target_file)
    other = AppSettings(None)
    reloaded: list[bool] = []
    other.reloaded.connect(lambda: reloaded.append(True))
    assert other.import_from(target_file) == []
    assert other.get_int("playback.seek_short") == 33
    assert other.get_str("state.window") == ""  # положение окна не переносится
    assert reloaded == [True]


def test_bad_import_changes_nothing(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    settings.set("playback.seek_short", 12)
    bad = tmp_path / "bad.toml"
    bad.write_text("= = =", encoding="utf-8")
    with pytest.raises(SettingsFileError):
        settings.import_from(bad)
    assert settings.get_int("playback.seek_short") == 12


def test_restart_required_changes_are_remembered(tmp_path: Path) -> None:
    settings = _store(tmp_path)
    settings.set("general.language", "en")
    settings.set("playback.seek_short", 6)
    assert settings.restart_pending == {"general.language"}


def test_import_from_previous_storage(tmp_path: Path) -> None:
    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    old.setValue("player/audio_langs", "jpn,eng")
    old.setValue("player/sub_font_size", 70)
    old.setValue("player/hwdec", "no")
    settings = AppSettings(None)
    settings.import_legacy(old)
    assert settings.get_str("playback.audio_langs") == "jpn,eng"
    assert settings.get_int("subtitles.font_size") == 70
    assert settings.get_str("playback.hwdec") == "off"
    assert settings.mpv_hwdec() == "no"


def test_unwritable_location_reports_instead_of_crashing(qtbot: QtBot, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    settings = AppSettings(blocker / "settings.toml")  # «папка» — на самом деле файл
    notices: list[str] = []
    settings.notice.connect(notices.append)
    settings.set("playback.seek_short", 9)
    settings.flush()
    assert notices and "сохранить" in notices[0]
    assert settings.get_int("playback.seek_short") == 9  # в памяти значение осталось
